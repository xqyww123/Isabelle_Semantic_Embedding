(*  Title:      Tools/entity_position.ML
    Author:     Qiyuan Xu

Entity positions -- (portable symbolic file path, line, byte column) for the
place an Isabelle entity is declared.  See ENTITY_POSITION_PLAN.md §5.
*)

signature ENTITY_POSITION = sig
  (* (portable symbolic file path, line, byte column); plan §1 defines all three. *)
  type entity_position = string * int * int
  type report = {no_file: int, unreadable: int, line_mismatch: int}
  (* Batch: absolutizes once, walks each file once.  The result is parallel to
     the argument -- NONE wherever no position could be established (plan §10). *)
  val of_positions : Position.T list -> entity_position option list * report
  (* The folding that produced the file component of EVERY stored position.
     Exposed so that anything comparing a path of its own against a stored one
     derives it the same way, instead of picking another File.* folding whose
     output differs on the same file (BUG_UNIVERSAL_KEY_SHORT_NAME_FIX_PLAN.md
     §B.3, the dump's per-theory source path). *)
  val portable_path : Path.T -> string
end

structure Entity_Position : ENTITY_POSITION = struct

type entity_position = string * int * int
type report = {no_file: int, unreadable: int, line_mismatch: int}


(* the portable symbolic file path *)

(* Only $AFP and ~~ are kept folded (plan L1').  File.symbolic_path also folds
   against ~ and $ISABELLE_HOME_USER, whose results look portable yet name a
   different file on a consumer's machine; those are stored absolute instead. *)
fun portable_path path =
  let val sym = File.symbolic_path path in
    if String.isPrefix "$AFP/" sym orelse String.isPrefix "~~/" sym
    then sym else File.standard_path path
  end


(* byte columns of one file *)

(* One walk over Pure's own symbol stream, consuming `targets` (ascending by
   symbol offset) as it goes.  Returns (key, (line, byte column)) for each
   offset that lies inside the file; offsets past EOF are simply absent.

   A symbol's `size` is its width on disk except in two cases, neither of which
   can shift a column.  Symbol.explode folds "\r\n" to a single "\n", which
   only shortens the run-up to a line start -- and the column is measured from
   that line start.  It also decodes the pseudo-UTF8 "\192"+control pair to one
   byte; no .thy file in Isabelle2025-2 or afp-2026-05-13 contains a \192 byte
   at all. *)
fun scan_columns text targets =
  let
    fun drain i line col ts acc =
      (case ts of
        (k, off) :: rest =>
          if off = i then drain i line col rest ((k, (line, col)) :: acc)
          else (ts, acc)
      | [] => ([], acc))
    fun walk syms i byte line line_byte ts acc =
      (case ts of
        [] => acc
      | _ =>
        (case syms of
          [] => acc
        | s :: ss =>
            let val (ts', acc') = drain i line (byte - line_byte + 1) ts acc in
              if null ts' then acc'
              else
                let val byte' = byte + size s in
                  if s = "\n" then walk ss (i + 1) byte' (line + 1) byte' ts' acc'
                  else walk ss (i + 1) byte' line line_byte ts' acc'
                end
            end))
  in walk (Symbol.explode text) 1 0 1 0 targets [] end


(* the batch entry point *)

fun of_positions positions =
  let
    val result = Array.array (length positions, NONE : entity_position option)
    val no_file = Unsynchronized.ref 0
    val unreadable = Unsynchronized.ref 0
    val line_mismatch = Unsynchronized.ref 0
    fun bump r k = r := ! r + k

    (* One Scala round trip for the whole batch; a no-op unless some position is
       ID-based, which only the interactive path produces. *)
    val resolved = PIDE_State.absolutize_id_based_pos {write_to_temp_file = false} positions

    (* Group by the EXPANDED path, so that a bare bootstrap name such as
       "drule.ML" is recognisable as non-absolute below and never resolved
       against the process working directory. *)
    val groups =
      fold_index (fn (i, pos) => fn tab =>
        (case (Position.file_of pos, Position.line_of pos, Position.offset_of pos) of
          (SOME f, SOME line, SOME off) =>
            if f = "" orelse line < 1 orelse off < 1 then (bump no_file 1; tab)
            else
              (case try (Path.expand o Path.explode) f of
                NONE => (bump unreadable 1; tab)
              | SOME p => Symtab.cons_list (File.standard_path p, (i, line, off)) tab)
        | _ => (bump no_file 1; tab))) resolved Symtab.empty

    fun process (key, targets) =
      let
        val path = Path.explode key
        val text = if Path.is_absolute path then \<^try>\<open>File.read path\<close> else NONE
      in
        (case text of
          NONE => bump unreadable (length targets)
        | SOME text =>
            let
              val file = portable_path path
              val sorted = sort (int_ord o apply2 #3) targets
              val found =
                scan_columns text (map (fn (i, line, off) => ((i, line), off)) sorted)
              (* Offsets past EOF are dropped by the walk.  Under plan L7 that
                 cannot legitimately happen, so they join the line mismatches:
                 both mean this module's arithmetic disagrees with Isabelle's. *)
              val _ = bump line_mismatch (length sorted - length found)
            in
              found |> List.app (fn ((i, line), (line', col)) =>
                (* The line assertion (plan §5.2): Isabelle advances `line` and
                   `offset` over one and the same symbol stream, so a disagreement
                   is a bug in the walk above, not an environment problem. *)
                if line = line' then Array.update (result, i, SOME (file, line, col))
                else bump line_mismatch 1)
            end)
      end
    val _ = List.app process (Symtab.dest groups)
  in
    (Array.foldr (op ::) [] result,
     {no_file = ! no_file, unreadable = ! unreadable, line_mismatch = ! line_mismatch})
  end

end
