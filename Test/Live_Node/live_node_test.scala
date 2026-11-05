/*  Unit test of PIDE_Query.live_node, same_file, node_path and live_or_db, the Scala
    live-node lookup (Isabelle2026 port).  No PIDE session: a hand-built Document.Nodes and a
    stub Resources.  Fixture files are made at run time in a fresh temporary directory under
    USER_HOME, removed afterwards, so that one node can carry the folded name a Headless
    session gives ("~/...").  Run:

      isabelle scala Test/Live_Node/live_node_test.scala

    It prints one "ok:" or "FAILED:" line per check and exits non-zero on a failure.
*/

import isabelle._
import isabelle.semantic_embedding.PIDE_Query

import java.nio.file.{Files, Path => JPath}

object Live_Node_Test {
  private var failures = 0

  private def check(name: String, ok: => Boolean): Unit = {
    val res = try { ok } catch { case exn: Throwable => println("raised: " + exn); false }
    if (res) println("ok: " + name) else { println("FAILED: " + name); failures += 1 }
  }

  def main(args: Array[String]): Unit = {
    Isabelle_System.with_tmp_dir("live_node_test", base_dir = Path.explode("~").file) { home =>
      val real = Isabelle_System.make_directory(home + Path.basic("real"))
      val a = real + Path.basic("A.thy")
      File.write(a, "theory A imports Pure begin end\n")
      val alias_dir = home + Path.basic("alias")
      Files.createSymbolicLink(alias_dir.java_path, real.java_path)
      val hard = Isabelle_System.make_directory(home + Path.basic("hard"))
      Files.createLink((hard + Path.basic("A.thy")).java_path, a.java_path)
      Files.createSymbolicLink((real + Path.basic("Other.thy")).java_path, a.java_path)
      // Path.explode rejects the apostrophe, so this one is built as a plain string
      val its_dir = home.implode + "/it's"
      val its_a = its_dir + "/A.thy"
      Files.createDirectories(JPath.of(its_dir))
      Files.writeString(JPath.of(its_a), "theory A imports Pure begin end\n")

      val bg = Resources.bootstrap.parent_background
      val resources = new Resources(bg, bg, Logger.none) {
        override def loaded_theory(name: Document.Node.Name): Boolean = name.theory == "HOL.Nat"
      }
      def nodes(names: Document.Node.Name*): Document.Nodes =
        names.foldLeft(Document.Nodes.empty)((ns, n) => ns + (n -> Document.Node.empty))
      def lookup(ns: Document.Nodes, file: String) = PIDE_Query.live_node(resources, ns, file)

      val folded = Document.Node.Name("~/" + home.file_name + "/real/A.thy")
      val its = Document.Node.Name(its_a)
      val graph = nodes(folded, its)
      val expanded = a.implode

      check("U-exact: a node Path.explode rejects is found by its own name",
        lookup(graph, its_a).map(_.node) == Some(its_a))
      check("U-fold: the expanded spelling finds the folded node",
        lookup(graph, expanded).isDefined)
      check("U-name: the graph's own name comes back, not the caller's spelling",
        lookup(graph, expanded).map(_.node) == Some(folded.node))
      check("U-symlink: through a directory symlink",
        lookup(graph, (alias_dir + Path.basic("A.thy")).implode).map(_.node) == Some(folded.node))
      check("U-hard: through a hard link",
        lookup(graph, (hard + Path.basic("A.thy")).implode).map(_.node) == Some(folded.node))
      check("U-alias: a link with another file name is not the same file",
        lookup(graph, (real + Path.basic("Other.thy")).implode).isEmpty)
      for (bad <- List("$LN_UNDEFINED/A.thy", "C:\\x\\A.thy", ""))
        check("U-reject: " + quote(bad), lookup(graph, bad).isEmpty)
      check("U-reject: a rejected spelling that names no node",
        lookup(nodes(folded), its_a).isEmpty)
      check("U-reject: a rejected node name next to a query for another file",
        lookup(nodes(its), expanded).isEmpty)
      check("U-loaded: a loaded-theory node is skipped, even by its exact name",
        lookup(nodes(Document.Node.Name(expanded, theory = "HOL.Nat")), expanded).isEmpty)

      // the live answer is empty (""), as on a blank line: it must still be the answer
      var db_calls = 0
      def route(ns: Document.Nodes, file: String): String =
        PIDE_Query.live_or_db(resources, ns, file)(_ => "", { db_calls += 1; "db" })
      check("U-route: a file with a live node never reaches the database",
        route(graph, expanded) == "" && db_calls == 0)
      check("U-route: a file with no live node gets the database's answer",
        route(nodes(its), expanded) == "db" && db_calls == 1)
    }
    if (failures > 0) { println(failures.toString + " FAILED"); sys.exit(1) }
    else println("Live_Node_Test: all checks passed")
  }
}
