/*  Title:      Semantic_Embedding/src/scala/pide_state.scala
    Author:     Qiyuan Xu

Scala functions for accessing PIDE document state from ML:
  - Save theory file contents (read-only: returns file/source pairs for ML to write)
  - Command ID to file+line position mapping
  - Go-to-definition: resolve entity reference at a position to its definition position
  - Hover message: extract tooltip information at a position
  - Command at position: retrieve source code of the command at a given position
  - Command id at position: the live node's own name and the command's id
The position queries answer from the live PIDE node holding the file (PIDE_Query.live_node:
a node PIDE parsed, found by its name or as the same file), else, when there is no live
node, from the build-time snapshot of the heap theory whose source the file is
(DB_Snapshots); PIDE_Query.live_or_db picks the one route.
*/

package isabelle.semantic_embedding

import isabelle._


/* Shared query helpers operating on any Document.Snapshot */

object PIDE_Query {
  /** Locate the command in a live PIDE node containing the given 1-based symbol
    * offset.  Returns the command and the 1-based symbol offset of its first
    * symbol (sym_pos), accumulating widths via command.span.symbol_length (the
    * authoritative symbol count) rather than chunk.range.stop (a char count). */
  def command_at_symbol_offset(
    node: Document.Node, offset: Int
  ): Option[(Command, Int)] = {
    var pos = 1
    val it = node.commands.iterator
    var found: Option[(Command, Int)] = None
    while (it.hasNext && found.isEmpty) {
      val c = it.next()
      val len = c.span.symbol_length
      if (offset >= pos && offset < pos + len) found = Some((c, pos))
      pos += len
    }
    found
  }

  /** The file a node name denotes, as Document.Node.Name.path reads it, expanded.
    * None if Path.explode or the expansion rejects it (an illegal character, an
    * undefined variable). */
  def node_path(name: Document.Node.Name): Option[Path] =
    try { Some(name.path.expand) } catch { case ERROR(_) => None }

  /** Same file, by the rule the ML file lookup uses: the same file name, then the
    * same OS file (File.eq). */
  def same_file(a: Document.Node.Name, b: Document.Node.Name): Boolean =
    a.file_name.nonEmpty && a.file_name == b.file_name &&
      ((node_path(a), node_path(b)) match {
        case (Some(p), Some(q)) => File.eq(p, q)
        case _ => false
      })

  /** The live node holding the file `file_path` names, as the graph's own Name: the node
    * of exactly that name, else the first (in node-name order) that is the same file.
    * Loaded-theory nodes are skipped: PIDE keeps a heap theory opened in an editor as one
    * unparsed command of the whole file and never parses it (Isabelle2026
    * thy_syntax.scala:307-311, 407-422); its session DB answers instead, as when no editor
    * has it open.  The one place that lists candidate nodes.  Never raises. */
  def live_node(resources: Resources, nodes: Document.Nodes, file_path: String)
    : Option[Document.Node.Name] =
  {
    val target = Document.Node.Name(file_path)
    def candidates = nodes.names_iterator.filterNot(name => resources.loaded_theory(name))
    candidates.find(_ == target) orElse candidates.find(same_file(_, target))
  }

  /** The answer for the file `file_path` names, from exactly one route: `live` on the node
    * live_node finds, else `db` (the build-time snapshot's answer).  A file with a live node
    * never reaches the database, even where its live answer is empty. */
  def live_or_db[A](resources: Resources, nodes: Document.Nodes, file_path: String)(
    live: Document.Node.Name => A, db: => A): A =
    live_node(resources, nodes, file_path) match {
      case Some(name) => live(name)
      case None => db
    }

  private def symbol_offset_to_range(
    snapshot: Document.Snapshot, offset: Int
  ): Text.Range = {
    // Isabelle2025-2: snippet_command: Option[Command] became
    // snippet_commands: List[Command]; our snippets carry one command.
    snapshot.snippet_commands match {
      case command :: _ =>
        // Snippet: convert from symbol offset to decoded text offset
        val start = command.chunk.decode(offset)
        val stop = command.chunk.decode(offset + 1)
        Text.Range(start, stop)
      case Nil =>
        // Live PIDE: `offset` is a 1-based *file-global symbol* offset.  Locate
        // the command containing it (accumulating span.symbol_length, the true
        // symbol count), then map the in-command symbol offset to a char offset
        // via chunk.decode and shift by the command's char start in the node.
        command_at_symbol_offset(snapshot.node, offset) match {
          case Some((command, sym_pos)) =>
            val local = offset - sym_pos + 1
            // command came from node.commands, so command_start always hits.
            val char_base = snapshot.node.command_start(command).get
            Text.Range(char_base + command.chunk.decode(local),
                       char_base + command.chunk.decode(local + 1))
          case None =>
            // offset out of [1, total_symbols]: degenerate empty range so the
            // caller's cumulate finds nothing (never reuse the old char≈symbol
            // assumption here).
            Text.Range(0, 0)
        }
    }
  }

  def goto_definition(snapshot: Document.Snapshot, offset: Int)
      : (String, Int, Int, Int) = {
    val range = symbol_offset_to_range(snapshot, offset)

    val links = snapshot.cumulate[List[(String, Int, Int, Int)]](
      range, Nil, Markup.Elements(Markup.ENTITY), _ => {
        case (acc, Text.Info(_, XML.Elem(Markup(Markup.ENTITY, props), _))) =>
          props match {
            case Position.Item_Def_File(name, line, def_range) =>
              Some((name, line, def_range.start, def_range.stop) :: acc)
            case Position.Item_Def_Id(id, def_range) =>
              snapshot.get_command(id) match {
                case Some(command) =>
                  val node = snapshot.command_node(command)
                  val name = command.node_name.node
                  val preceding_symbols =
                    node.commands.iterator.takeWhile(_ != command)
                      .map(_.span.symbol_length).sum
                  val within_lines =
                    if (def_range.start <= 0) 0
                    else {
                      val decoded = command.chunk.decode(def_range.start)
                      Text.Range(0, decoded).try_substring(command.source) match {
                        case Some(text) => Library.count_newlines(text)
                        case None => 0
                      }
                    }
                  val line = node.command_start_line(command).getOrElse(1) + within_lines
                  Some((name, line,
                        preceding_symbols + def_range.start,
                        preceding_symbols + def_range.stop) :: acc)
                case None => None
              }
            case _ => None
          }
        case _ => None
      })

    links match {
      case Text.Info(_, result :: _) :: _ => result
      case _ => ("", 0, 0, 0)
    }
  }

  private val tooltip_elements = Markup.Elements(
    Markup.ENTITY, Markup.TYPING, Markup.SORTING, Markup.ML_TYPING)

  def entity_at_position(snapshot: Document.Snapshot, offset: Int)
      : (String, String) = {
    val range = symbol_offset_to_range(snapshot, offset)

    val results = snapshot.cumulate[(String, String)](
      range, ("", ""), Markup.Elements(Markup.ENTITY), _ => {
        case (("", ""), Text.Info(_, XML.Elem(Markup.Entity(entry), _)))
          if entry.kind != "" && entry.kind != Markup.ML_DEF =>
          Some((entry.kind, entry.name))
        case _ => None
      })

    results match {
      case Text.Info(_, result) :: _ if result != ("", "") => result
      case _ => ("", "")
    }
  }

  def command_at_position(node: Document.Node, offset: Int): (String, Int, Int) = {
    command_at_symbol_offset(node, offset) match {
      case Some((command, pos)) =>
        (command.source, pos, pos + command.span.symbol_length)
      case None => ("", 0, 0)
    }
  }

  def command_at_position(snapshot: Document.Snapshot, offset: Int): (String, Int, Int) = {
    val range = symbol_offset_to_range(snapshot, offset)

    val spans = snapshot.cumulate[Option[Text.Range]](
      range, None, Markup.Elements(Markup.COMMAND_SPAN), _ => {
        case (None, Text.Info(info_range, _)) => Some(Some(info_range))
        case _ => None
      })

    spans match {
      case Text.Info(_, Some(span_range)) :: _ =>
        snapshot.snippet_commands match {
          case command :: _ =>
            // DB snippet: ranges are in decoded text offsets, need to extract source substring
            val src = span_range.try_substring(command.source).getOrElse("")
            // Convert decoded text offsets back to symbol offsets for the return value
            val chunk = command.chunk
            // Invert: find symbol offsets that decode to span_range.start/stop
            // Use a linear scan of symbol positions
            val sym_start = symbol_offset_of_decoded(chunk, span_range.start)
            val sym_stop = symbol_offset_of_decoded(chunk, span_range.stop)
            (src, sym_start, sym_stop)
          case Nil =>
            // Live PIDE: shouldn't reach here, but handle gracefully
            ("", 0, 0)
        }
      case _ => ("", 0, 0)
    }
  }

  /** Find the 1-based symbol offset whose decoded text offset is >= target.
    * This inverts Text_Chunk.decode for the purpose of returning symbol offsets. */
  private def symbol_offset_of_decoded(chunk: Symbol.Text_Chunk, target: Int): Int = {
    // Binary search: find smallest symbol offset s such that chunk.decode(s) >= target
    var lo = 1
    var hi = chunk.range.stop + 1  // upper bound: one past the last symbol
    while (lo < hi) {
      val mid = (lo + hi) / 2
      if (chunk.decode(mid) < target) lo = mid + 1
      else hi = mid
    }
    lo
  }

  def hover_message(snapshot: Document.Snapshot, offset: Int): String = {
    val range = symbol_offset_to_range(snapshot, offset)

    val results = snapshot.cumulate[List[String]](
      range, Nil, tooltip_elements, _ => {
        // As Rendering.tooltips: one line per entity element, so a name with several
        // positions (e.g. a constant made by a locale interpretation) gives one line
        // per position, each with its def_label.
        case (tips, Text.Info(_, XML.Elem(Markup.Entity(entry), _)))
          if entry.kind != "" && entry.kind != Markup.ML_DEF =>
          Some(entry.print() :: tips)

        case (tips, Text.Info(_, XML.Elem(Markup(name, _), body)))
          if name == Markup.TYPING || name == Markup.SORTING =>
          val body_text = XML.content(Pretty.formatted(body))
          Some((":: " + body_text) :: tips)

        case (tips, Text.Info(_, XML.Elem(Markup(Markup.ML_TYPING, _), body))) =>
          val body_text = XML.content(Pretty.formatted(body))
          Some(("ML: " + body_text) :: tips)

        case _ => None
      })

    results match {
      case Text.Info(_, tips) :: _ => tips.reverse.mkString("\n")
      case _ => ""
    }
  }
}


/* Export-DB snapshots: Isabelle's own file -> heap theory -> build-time snapshot route */

object DB_Snapshots {
  /* The heap theory whose source is `file`: Isabelle's file-to-theory map
     (Resources.find_theory, as JEdit_Resources.node_name uses it), restricted to what
     Session.read_theory reads: parent_background's cumulative loaded theories.  So a file
     is answered only from the build-time snapshot of the very theory the heap loaded from
     it -- never by base name or content from another file, and never from the session a
     batch build is building (parent_background excludes it). */
  def heap_theory(resources: Resources, file: Path): Option[String] =
    resources.find_theory(file.file).map(_.theory)
      .filter(theory => resources.parent_background.base.loaded_theory(theory))

  // per Session (its heap): Session.read_theory's own cache is weak and cleared at GC
  private val snapshots =
    new java.util.WeakHashMap[Session, Map[String, Option[Document.Snapshot]]]

  private def read_theory(session: Session, theory: String): Option[Document.Snapshot] =
    snapshots.synchronized {
      val found = snapshots.get(session)
      val cache = if (found == null) Map.empty[String, Option[Document.Snapshot]] else found
      cache.getOrElse(theory, {
        val result =
          try { Some(session.read_theory(theory)) }
          catch {
            case exn: Exception if !Exn.is_interrupt(exn) =>
              Output.warning("DB_Snapshots: " + Exn.message(exn)); None
          }
        snapshots.put(session, cache + (theory -> result))
        result
      })
    }

  def get_snapshot(session: Session, file_path: String): Option[Document.Snapshot] =
    for {
      path <- PIDE_Query.node_path(Document.Node.Name(file_path)).filter(_.is_file)
      theory <- heap_theory(session.resources, path)
      snapshot <- read_theory(session, theory)
    } yield snapshot
}


object Save_Thy_Files extends Scala.Fun("pide_state.save_thy_files", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  private var last_max_id: Map[String, Long] = Map.empty

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val version = session.get_state().recent_finished.version.get_finished

    val written: List[String] =
      (for {
        (name, node) <- version.nodes.iterator
        if name.is_theory
        src = node.source
        if src.nonEmpty
      } yield {
        val max_id = node.commands.iterator.map(_.id).maxOption.getOrElse(0L)
        val cached = last_max_id.getOrElse(name.node, -1L)
        if (max_id == cached) None
        else {
          val backup = Path.explode(name.node + "~")
          val existing = try { File.read(backup) } catch { case _: Exception => "" }
          if (existing == src) {
            last_max_id += (name.node -> max_id)
            None
          }
          else {
            File.write(backup, src)
            last_max_id += (name.node -> max_id)
            Some(backup.implode)
          }
        }
      }).flatten.toList

    val body = XML.Encode.list(XML.Encode.string)(written)
    List(Bytes(YXML.string_of_body(body)))
  }
}


object Resolve_Positions extends Scala.Fun("pide_state.resolve_positions", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val input =
      XML.Decode.list(XML.Decode.pair(XML.Decode.long, XML.Decode.int))(
        YXML.parse_body(YXML.Source(args.head.text)))

    val snapshot = session.get_state().snapshot()

    // Init: resolve commands, collect unique nodes
    val resolved = new scala.collection.mutable.HashMap[Long, (Document.Node, Command)]
    val nodes_to_scan = new scala.collection.mutable.LinkedHashSet[Document.Node]
    for ((id, _) <- input) {
      if (!resolved.contains(id)) {
        snapshot.get_command(id) match {
          case Some(command) =>
            val node = snapshot.command_node(command)
            resolved(id) = (node, command)
            nodes_to_scan += node
          case None =>
        }
      }
    }

    // Scan: single pass per node to compute preceding symbol counts
    val needed_ids = resolved.values.map(_._2.id).toSet
    val preceding_symbols_map = new scala.collection.mutable.HashMap[Document_ID.Command, Int]
    for (node <- nodes_to_scan) {
      var symbols = 0
      for (command <- node.commands.iterator) {
        if (needed_ids.contains(command.id)) {
          preceding_symbols_map(command.id) = symbols
        }
        symbols += command.span.symbol_length
      }
    }

    // Resolve: look up precomputed data, compute within-command line offset
    val results: List[(String, (Int, Int))] =
      input.map { case (id, offset) =>
        resolved.get(id) match {
          case Some((node, command)) =>
            val preceding_symbols = preceding_symbols_map.getOrElse(command.id, 0)
            val start_line = node.command_start_line(command).getOrElse(1)
            val within_lines =
              if (offset <= 1) 0
              else {
                val decoded = command.chunk.decode(offset)
                val range = Text.Range(0, decoded)
                range.try_substring(command.source) match {
                  case Some(text) => Library.count_newlines(text)
                  case None => 0
                }
              }
            (command.node_name.node, (start_line + within_lines, preceding_symbols))
          case None => ("", (0, 0))
        }
      }

    val body =
      XML.Encode.list(
        XML.Encode.pair(XML.Encode.string,
          XML.Encode.pair(XML.Encode.int, XML.Encode.int))
      )(results)
    List(Bytes(YXML.string_of_body(body)))
  }
}


object Goto_Definition extends Scala.Fun("pide_state.goto_definition", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val (file_path, offset) =
      XML.Decode.pair(XML.Decode.string, XML.Decode.int)(
        YXML.parse_body(YXML.Source(args.head.text)))

    val state = session.get_state()
    val version = state.recent_finished.version.get_finished

    val result =
      PIDE_Query.live_or_db(session.resources, version.nodes, file_path)(
        name => PIDE_Query.goto_definition(state.snapshot(node_name = name), offset),
        DB_Snapshots.get_snapshot(session, file_path)
          .map(PIDE_Query.goto_definition(_, offset)).getOrElse(("", 0, 0, 0)))

    val body = {
      val (a, b, c, d) = result
      XML.Encode.pair(XML.Encode.string,
        XML.Encode.pair(XML.Encode.int,
          XML.Encode.pair(XML.Encode.int, XML.Encode.int)))((a, (b, (c, d))))
    }
    List(Bytes(YXML.string_of_body(body)))
  }
}


object Hover_Message extends Scala.Fun("pide_state.hover_message", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val (file_path, offset) =
      XML.Decode.pair(XML.Decode.string, XML.Decode.int)(
        YXML.parse_body(YXML.Source(args.head.text)))

    val state = session.get_state()
    val version = state.recent_finished.version.get_finished

    val result =
      PIDE_Query.live_or_db(session.resources, version.nodes, file_path)(
        name => PIDE_Query.hover_message(state.snapshot(node_name = name), offset),
        DB_Snapshots.get_snapshot(session, file_path)
          .map(PIDE_Query.hover_message(_, offset)).getOrElse(""))

    List(Bytes(YXML.string_of_body(XML.Encode.string(result))))
  }
}


object Entity_At_Position extends Scala.Fun("pide_state.entity_at_position", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val (file_path, offset) =
      XML.Decode.pair(XML.Decode.string, XML.Decode.int)(
        YXML.parse_body(YXML.Source(args.head.text)))

    val state = session.get_state()
    val version = state.recent_finished.version.get_finished

    val result =
      PIDE_Query.live_or_db(session.resources, version.nodes, file_path)(
        name => PIDE_Query.entity_at_position(state.snapshot(node_name = name), offset),
        DB_Snapshots.get_snapshot(session, file_path)
          .map(PIDE_Query.entity_at_position(_, offset)).getOrElse(("", "")))

    val body = XML.Encode.pair(XML.Encode.string, XML.Encode.string)(result)
    List(Bytes(YXML.string_of_body(body)))
  }
}


object Command_At_Position extends Scala.Fun("pide_state.command_at_position", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val (file_path, offset) =
      XML.Decode.pair(XML.Decode.string, XML.Decode.int)(
        YXML.parse_body(YXML.Source(args.head.text)))

    val state = session.get_state()
    val version = state.recent_finished.version.get_finished

    // the node of the recent_finished version (version.nodes), not state.snapshot's
    val result =
      PIDE_Query.live_or_db(session.resources, version.nodes, file_path)(
        name => PIDE_Query.command_at_position(version.nodes(name), offset),
        DB_Snapshots.get_snapshot(session, file_path)
          .map(PIDE_Query.command_at_position(_, offset)).getOrElse(("", 0, 0)))

    val body = XML.Encode.pair(XML.Encode.string,
      XML.Encode.pair(XML.Encode.int, XML.Encode.int))(
        (result._1, (result._2, result._3)))
    List(Bytes(YXML.string_of_body(body)))
  }
}


object Get_Session_Databases extends Scala.Fun("pide_state.get_session_databases", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val store = Store(session.session_options)
    val sessions_structure = session.resources.sessions_structure
    val current_session = session.resources.current_background.session_name
    val ancestors = sessions_structure.build_hierarchy(current_session)

    val results: List[(String, String)] = ancestors.flatMap { name =>
      val s = store.get_session(name)
      s.log_db.map(path => (name, File.standard_path(path)))
    }

    val body = XML.Encode.list(
      XML.Encode.pair(XML.Encode.string, XML.Encode.string))(results)
    List(Bytes(YXML.string_of_body(body)))
  }
}


object Command_ID_At_Position extends Scala.Fun("pide_state.command_id_at_position", thread = true)
  with Scala.Single_Fun
{
  val here = Scala_Project.here

  override def invoke(session: Session, args: List[Bytes]): List[Bytes] = {
    val (file_path, offset) =
      XML.Decode.pair(XML.Decode.string, XML.Decode.int)(
        YXML.parse_body(YXML.Source(args.head.text)))

    val nodes = session.get_state().recent_finished.version.get_finished.nodes
    // the node's own name with the id: Document.command_exec knows a node by that name only
    val result: Option[(String, Long)] =
      for {
        name <- PIDE_Query.live_node(session.resources, nodes, file_path)
        (command, _) <- PIDE_Query.command_at_symbol_offset(nodes(name), offset)
      } yield (name.node, command.id)

    List(Bytes(YXML.string_of_body(
      XML.Encode.option(XML.Encode.pair(XML.Encode.string, XML.Encode.long))(result))))
  }
}


class PIDE_State_Functions extends Scala.Functions(
  Save_Thy_Files, Resolve_Positions, Goto_Definition, Hover_Message,
  Entity_At_Position, Command_At_Position, Get_Session_Databases,
  Command_ID_At_Position)
