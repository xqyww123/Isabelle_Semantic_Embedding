(*
  The linking cache (LINK_LAYER_PLAN.md §4.2, §8 step 4; D44 as revised by D48,
  D54, D68): one per lineage, a text table and a key table keyed by the exact
  term.  The pins read the change of Link_Finder's test counters over a call: the
  texts printed, the propositions keyed, and the entries the call found unfinished
  (none means it forked nothing).  A call in a proof records the links it saw; a
  later call that compares with them fails if that record is missing, so the pins
  never rest on an order they did not check.  The counters and the record are
  process-wide, so the commands must run one at a time with no other theory
  calling the finder: the REPL runs them so, the checks in proofs are ML_prf
  (PIDE forks a diagnostic ML_val, not ML_prf), and Test/ROOT gives this theory
  a session of its own with parallel_proofs = 0.
*)
theory Link_Finder_Cache_Test
  imports Semantic_Embedding_Test.Link_Finder_Test_Base
begin

ML \<open>
structure Cache_Test =
struct

open Link_Finder_Test

(*the value of f () and the change of the counters over it: (printed, keyed, unfinished)*)
fun counted f =
  let
    val c0 = Link_Finder.counters ();
    val x = f ();
    val c1 = Link_Finder.counters ();
  in (x, (#printed c1 - #printed c0, #keyed c1 - #keyed c0, #unfinished c1 - #unfinished c0)) end;

fun links ctxt = counted (fn () => Link_Finder.links ctxt);

(*a fresh lineage of a locale*)
fun fresh thy loc = Named_Target.init [] (Locale.check_global thy (loc, Position.none)) thy;

(*every text a link carries*)
fun texts (_, l: Link_Finder.link) =
  #statement l :: map #text (#params l) @ maps (fn (a, b) => [a, b]) (#rewrites l) @
    map #1 (#entities l);

(*a link with its texts left out*)
fun untexted (k, l: Link_Finder.link) =
  (k, #template l, #source l, #note l, map (fn p => (#verdict p, #name p)) (#params l),
   length (#rewrites l), map #2 (#entities l), #level l);

(*the distinct texts of the links that no earlier link carries*)
fun new_texts earlier ls = subtract (op =) (maps texts earlier) (distinct (op =) (maps texts ls));

(*the keys a link carries: the fact's and the template's*)
fun keys_of (k, l: Link_Finder.link) = [k, #template l];

(*the distinct keys of the links that no earlier link carries*)
fun new_keys earlier ls = subtract (op =) (maps keys_of earlier) (distinct (op =) (maps keys_of ls));

(*the links a call recorded under a label*)
val seen = Synchronized.var \<^unchecked_name>\<open>Cache_Test.seen\<close>
  (Symtab.empty: (Universal_Key.universal_key * Link_Finder.link) list Symtab.table);
fun see label ls = Synchronized.change seen (Symtab.update (label, ls));
fun saw label =
  (case Symtab.lookup (Synchronized.value seen) label of
    SOME ls => ls
  | NONE => fail ("no call recorded as " ^ label ^ ": the calls ran out of order"));

(*the one link of a note's first theorem*)
fun the_link ls note =
  (case filter (fn (_, l: Link_Finder.link) => #note l = (note, 0)) ls of
    [kl] => kl
  | kls => fail (string_of_int (length kls) ^ " links of the note " ^ note));

(*the facts the finder linked, by name*)
fun linked_names ctxt =
  #elements (#2 (report_in ctxt "linked names"))
  |> map_filter (fn {name, outcome = Link_Finder.Linked _, ...} => SOME name | _ => NONE);

(*alpha-variant facts, each given as (its name, its template's global name, its
  statement): each link has its own fact's key, its own template's key and its own
  text (D68)*)
fun check_alpha_variants label ctxt ls variants =
  let
    val thy = Proof_Context.theory_of ctxt;
    val kls = map (fn (name, _, _) => the_link ls name) variants;
    fun fact_key name =
      Universal_Key.key_of_theorem' NONE (Context.Proof ctxt) (Proof_Context.get_thm ctxt name);
    fun template_key name =
      Universal_Key.key_of_theorem' NONE (Context.Theory thy) (Global_Theory.get_thm thy name);
    fun different xs = length (distinct (op =) xs) = length xs;
  in
    check_all label
     [("each link has its own fact's key, and the keys differ", fn () =>
        map #1 kls = map (fact_key o #1) variants andalso different (map #1 kls)),
      ("each has its own template's key, and these differ", fn () =>
        map (#template o #2) kls = map (template_key o #2) variants andalso
        different (map (#template o #2) kls)),
      ("each shows its own statement", fn () => map (#statement o #2) kls = map #3 variants)]
  end;

end
\<close>


section \<open>A repeated call\<close>

ML \<open>
local open Cache_Test
  val ctxt = fresh \<^theory> "linorder"
  val (l1, (p1, k1, _)) = links ctxt
  val (l2, c2) = links ctxt
  val (l3, c3) = links (#2 (Variable.add_fixes ["cache_x"] ctxt))
in
  val _ = check_all "a repeated call"
   [("the first call prints and keys", fn () => p1 > 0 andalso k1 > 0),
    ("a repeated call prints nothing, keys nothing and finds no entry unfinished, so forks \
      \nothing", fn () => c2 = (0, 0, 0)),
    ("and returns the same links", fn () => l2 = l1),
    ("a context derived from the first shares its cache", fn () =>
      c3 = (0, 0, 0) andalso l3 = l1)]
end
\<close>


section \<open>Two calls in parallel on two contexts of one lineage\<close>

ML \<open>
local open Cache_Test
  val thy = \<^theory>
  val (sequential, (p, k, _)) = links (fresh thy "linorder")
  val base = fresh thy "linorder"
  val cs = map (fn x => #2 (Variable.add_fixes [x] base)) ["cache_a", "cache_b"]
  val (parallel, (q, kq, _)) = counted (fn () => Par_List.map Link_Finder.links cs)
in
  val _ = check_all "two calls in parallel"
   [("print each text once and key each proposition once", fn () => q = p andalso kq = k),
    ("and give the links of a sequential run", fn () => parallel = [sequential, sequential])]
end
\<close>


section \<open>A print option of the context\<close>

text \<open>A config declared in a class block reaches the whole theory (probed on 2026-10-28), so
  the reference links are taken before it and the option is switched off after the block.\<close>

ML \<open>Cache_Test.see "before names_long" (#1 (Cache_Test.links (Cache_Test.fresh \<^theory> "linorder")))\<close>

context linorder
begin

declare [[names_long]]

ML \<open>
local open Cache_Test
  val ctxt = \<^context>
  val reference = saw "before names_long"
  val (ls, _) = links ctxt
in
  val _ = check_all "a print option"
   [("names_long is set in the block", fn () => Config.get ctxt Name_Space.names_long),
    ("declare [[names_long]] leaves the link texts unchanged", fn () =>
      map texts ls = map texts reference)]
end
\<close>

end

declare [[names_long = false]]


section \<open>Two statements that differ only in a bound-variable name (D68)\<close>

locale AV = fixes P :: "nat \<Rightarrow> bool" assumes allP: "\<forall>x. P x"

context AV
begin

lemma av1: "\<forall>x. P x" by (rule allP)

ML \<open>Cache_Test.see "av1" (#1 (Cache_Test.links \<^context>))\<close>

lemma av2: "\<forall>y. P y" by (rule allP)

ML \<open>
local open Cache_Test
  val ctxt = \<^context>
  val _ = saw "av1"
  val (ls, _) = links ctxt
in
  val _ = check_alpha_variants "alpha variants met in two calls of one block" ctxt ls
    [("av1", \<^unchecked_name>\<open>Link_Finder_Cache_Test.AV.av1\<close>, "\<forall>x. P x"),
     ("av2", \<^unchecked_name>\<open>Link_Finder_Cache_Test.AV.av2\<close>, "\<forall>y. P y")]
end
\<close>

end

ML \<open>
local open Cache_Test
  val ctxt = fresh \<^theory> "AV"
  val (ls, _) = links ctxt
in
  val _ = check_alpha_variants "alpha variants met first in one call" ctxt ls
    [("av1", \<^unchecked_name>\<open>Link_Finder_Cache_Test.AV.av1\<close>, "\<forall>x. P x"),
     ("av2", \<^unchecked_name>\<open>Link_Finder_Cache_Test.AV.av2\<close>, "\<forall>y. P y")]
end
\<close>


text \<open>Met in two calls of one lineage, from one block state: the later call prints and keys
  only what the later variant adds.\<close>

locale AW = fixes Q :: "nat \<Rightarrow> bool" assumes allQ: "\<forall>n. Q n \<and> True"

context AW
begin

ML \<open>
local open Cache_Test
  val lthy = \<^context>
  fun noted b s =
    let
      val th = Goal.prove lthy [] [] (Syntax.read_prop lthy s)
        (fn {context, ...} =>
          simp_tac (Simplifier.add_simp (Proof_Context.get_thm context "allQ") context) 1)
    in #2 (Local_Theory.note ((Binding.name b, []), [th]) lthy) end
  val cx = noted "awx" "\<forall>x. Q x" and cy = noted "awy" "\<forall>y. Q y"
  val (lx, _) = links cx
  val (ly, (p, k, _)) = links cy
  val keyx = Universal_Key.key_of_theorem' NONE (Context.Proof cx) (Proof_Context.get_thm cx "awx")
  val keyy = Universal_Key.key_of_theorem' NONE (Context.Proof cy) (Proof_Context.get_thm cy "awy")
in
  val _ = check_all "alpha variants met in two calls of one lineage"
   [("have keys of their own that differ (term128 hashes bound-variable names)", fn () =>
      keyx <> keyy),
    ("each keeps its own key", fn () =>
      #1 (the_link lx "awx") = keyx andalso #1 (the_link ly "awy") = keyy),
    ("and its own text", fn () => #statement (#2 (the_link ly "awy")) = "\<forall>y. Q y"),
    ("the later call prints and keys only what is new", fn () =>
      p = length (new_texts lx ly) andalso k = length (new_keys lx ly))]
end
\<close>

end


section \<open>A key does not depend on the context it is read in\<close>

text \<open>The key table holds the facts' keys, read in the proof context, and the templates',
  read in the theory, one entry per proposition.  The constituents are computed afresh here:
  through \<open>key_of_theorem'\<close> the pin would pass whatever the context, since the constituents
  cache returns the first computation.\<close>

ML \<open>
local open Cache_Test
  val thy = \<^theory>
  val ctxt = fresh thy "linorder"
  val props =
    Facts.dest_static false [Global_Theory.facts_of thy] (Proof_Context.facts_of ctxt)
    |> maps (map Thm.prop_of o #2)
  fun constituents context t =
    let val (h, cs, _) = Universal_Key.compute_constituents context t in (h, cs) end
in
  val _ = check_all "a key read in the proof context or in the theory"
   [("linorder has local facts", fn () => length props > 100),
    ("whose constituents agree between the proof context and the theory", fn () =>
      forall (fn t => constituents (Context.Proof ctxt) t = constituents (Context.Theory thy) t)
        props)]
end
\<close>

text \<open>A fact whose proposition is its template's: the two share one entry of the key table.\<close>

locale L0 = fixes f :: "'a \<Rightarrow> 'a"
begin
lemma triv: "(x::nat) = x" by (rule refl)
end

ML \<open>
local open Cache_Test
  val thy = \<^theory>
  val ctxt = fresh thy "L0"
  val (ls, _) = links ctxt
  val (k, l) = the_link ls "triv"
  val fact = Proof_Context.get_thm ctxt "triv"
  val template = Global_Theory.get_thm thy \<^unchecked_name>\<open>Link_Finder_Cache_Test.L0.triv\<close>
in
  val _ = check_all "a fact and its template with one proposition"
   [("have one proposition", fn () => Thm.prop_of fact = Thm.prop_of template),
    ("the link has the fact's own key", fn () =>
      k = Universal_Key.key_of_theorem' NONE (Context.Proof ctxt) fact),
    ("and the template's key", fn () =>
      #template l = Universal_Key.key_of_theorem' NONE (Context.Theory thy) template)]
end
\<close>


section \<open>Commands between two calls: nothing is printed or keyed again\<close>

text \<open>A bundle with local notation, for the proofs \<open>including\<close> it here and below.\<close>

definition lj :: "nat \<Rightarrow> nat \<Rightarrow> nat" where "lj a b = a + b"

bundle lj_syntax
begin
notation lj (infixl \<open>\<oplus>\<close> 65)
end

locale CB = fixes f :: "nat \<Rightarrow> nat" assumes fx: "f 0 = 0"

locale CM = fixes g :: "nat \<Rightarrow> nat"
begin
lemma cm: "g 1 = g 1" by (rule refl)
end

context CB
begin

ML \<open>Cache_Test.see "cb0" (#1 (Cache_Test.links \<^context>))\<close>

lemma cb_lemma: "f (f 0) = 0" by (simp add: fx)

ML \<open>
local open Cache_Test
  val earlier = saw "cb0"
  val (ls, (p, k, _)) = links \<^context>
in
  val _ = see "cb1" ls
  val _ = check_all "a lemma between two calls"
   [("gets its link", fn () => can (the_link ls) "cb_lemma"),
    ("and only its new texts are printed and its new keys keyed", fn () =>
      p = length (new_texts earlier ls) andalso k = length (new_keys earlier ls))]
end
\<close>

definition cb_c :: nat where "cb_c = f 1"

ML \<open>
local open Cache_Test
  val earlier = saw "cb0" @ saw "cb1"
  val (ls, (p, k, _)) = links \<^context>
in
  val _ = see "cb2" ls
  val _ = check_all "a NoSyn definition between two calls"
   [("gets its link", fn () => can (the_link ls) "cb_c_def"),
    ("and only its new texts are printed and its new keys keyed", fn () =>
      p = length (new_texts earlier ls) andalso k = length (new_keys earlier ls))]
end
\<close>

sublocale cm: CM f .

ML \<open>
local open Cache_Test
  val earlier = saw "cb0" @ saw "cb1" @ saw "cb2"
  val (ls, (p, k, _)) = links \<^context>
in
  val _ = see "cb3" ls
  val _ = check_all "an in-block sublocale between two calls"
   [("gets its links", fn () => #source (#2 (the_link ls "cm")) = \<^locale>\<open>Link_Finder_Cache_Test.CM\<close>),
    ("and only their new texts are printed and their new keys keyed", fn () =>
      p = length (new_texts earlier ls) andalso k = length (new_keys earlier ls))]
end
\<close>

lemma True
  including lj_syntax
proof -
  ML_prf \<open>
    local open Cache_Test
      val earlier = saw "cb3"
      val (ls, c) = links \<^context>
    in
      val _ = check_all "a proof under including"
       [("prints nothing, keys nothing and forks nothing", fn () => c = (0, 0, 0)),
        ("and returns the block's links", fn () => ls = earlier)]
    end
  \<close>
  show ?thesis ..
qed

lemma True
proof -
  have fx: "f 0 + 0 = 0" by (simp add: fx)
  ML_prf \<open>
    local open Cache_Test
      val ctxt = \<^context>
      val earlier = saw "cb3"
      val (ls, c) = links ctxt
      val (_, r) = report_in ctxt "a shadowing have"
    in
      val _ = check_all "a shadowing have"
       [("is Level 0", fn () =>
          #outcome (the_element (#elements r) \<^unchecked_name>\<open>local.fx\<close> 0) = Link_Finder.Rebound),
        ("gets no link and is never printed", fn () =>
          c = (0, 0, 0) andalso not (member (op =) (map (#statement o #2) ls) "f 0 + 0 = 0")),
        ("and the shadowed fact's link is gone", fn () =>
          ls = filter_out (fn (_, l) => #note l = ("fx", 0)) earlier)]
    end
  \<close>
  show ?thesis ..
qed

end


section \<open>Proof interpretations\<close>

locale IA = fixes h :: "nat \<Rightarrow> nat"
begin
lemma ia: "h 0 = h 0" by (rule refl)
lemma ib: "h 1 = h 1" by (rule refl)
end

locale IB = fixes k :: nat

context IB
begin

ML \<open>Cache_Test.see "ib0" (#1 (Cache_Test.links \<^context>))\<close>

lemma True
proof -
  interpret i: IA Suc .
  ML_prf \<open>
    local open Cache_Test
      val ctxt = \<^context>
      val earlier = saw "ib0"
      val (ls, (p, k, _)) = links ctxt
    in
      val _ = see "i1" ls
      val _ = check_all "a proof interpretation"
       [("links its facts", fn () =>
          subset (op =)
            ([\<^unchecked_name>\<open>local.i.ia\<close>,
              \<^unchecked_name>\<open>local.i.ib\<close>], linked_names ctxt)),
        ("and prints only its new texts and keys only its new keys", fn () =>
          p = length (new_texts earlier ls) andalso k = length (new_keys earlier ls))]
    end
  \<close>
  show ?thesis ..
qed

lemma True
proof -
  interpret i: IA Suc .
  ML_prf \<open>
    local open Cache_Test
      val ctxt = \<^context>
      val earlier = saw "i1"
      val (ls, c) = links ctxt
    in
      val _ = see "i2" ls
      val _ = check_all "the same interpretation in a second proof"
       [("links its facts", fn () =>
          subset (op =)
            ([\<^unchecked_name>\<open>local.i.ia\<close>,
              \<^unchecked_name>\<open>local.i.ib\<close>], linked_names ctxt)),
        ("prints and keys nothing and gives the first proof's links", fn () =>
          c = (0, 0, 0) andalso ls = earlier)]
    end
  \<close>
  show ?thesis ..
qed

lemma True
proof -
  interpret j: IA Suc .
  ML_prf \<open>
    local open Cache_Test
      val ctxt = \<^context>
      val earlier = saw "i2"
      val (ls, c) = links ctxt
    in
      val _ = see "j" ls
      val _ = check_all "the interpretation under another prefix"
       [("links each fact under its own name", fn () =>
          subset (op =)
            ([\<^unchecked_name>\<open>local.j.ia\<close>,
              \<^unchecked_name>\<open>local.j.ib\<close>], linked_names ctxt) andalso
          not (member (op =) (linked_names ctxt) \<^unchecked_name>\<open>local.i.ia\<close>)),
        ("prints and keys nothing and gives the same links", fn () =>
          c = (0, 0, 0) andalso ls = earlier)]
    end
  \<close>
  show ?thesis ..
qed

lemma True
proof -
  interpret i: IA Suc rewrites "Suc 0 = 1" by simp
  ML_prf \<open>
    local open Cache_Test
      val ctxt = \<^context>
      val earlier = saw "ib0" @ saw "i1" @ saw "i2" @ saw "j"
      val (ls, (p, k, _)) = links ctxt
      val statements = map (#statement o #2) ls
    in
      val _ = check_all "the interpretation with other rewrites"
       [("links the rewritten fact with its own statement", fn () =>
          subset (op =)
            ([\<^unchecked_name>\<open>local.i.ia\<close>,
              \<^unchecked_name>\<open>local.i.ib\<close>], linked_names ctxt) andalso
          #statement (#2 (the_link ls "ia")) = "1 = 1" andalso
          not (member (op =) statements "Suc 0 = Suc 0")),
        ("and prints only the new texts and keys only the new keys", fn () =>
          p = length (new_texts earlier ls) andalso k = length (new_keys earlier ls))]
    end
  \<close>
  show ?thesis ..
qed

lemma True
proof -
  interpret i: IA Suc .
  ML_prf \<open>Cache_Test.see "two1" (#1 (Cache_Test.links \<^context>))\<close>
  interpret j: IA "\<lambda>n. n + 2" .
  ML_prf \<open>
    local open Cache_Test
      val ctxt = \<^context>
      val first = saw "two1"
      val (ls, _) = links ctxt
    in
      val _ = check_all "two interpretations in one proof"
       [("keep the first one's links", fn () => subset (op =) (first, ls)),
        ("and add the second one's", fn () =>
          subset (op =)
            ([\<^unchecked_name>\<open>local.i.ia\<close>,
              \<^unchecked_name>\<open>local.j.ia\<close>], linked_names ctxt) andalso
          exists (fn (_, l) => exists (fn p => #text p = "\<lambda>n. n + 2") (#params l)) ls)]
    end
  \<close>
  show ?thesis ..
qed

end


section \<open>A lemma executed again after an edit\<close>

text \<open>Two notes of one name from the same block state stand for a lemma and its edited
  re-execution under PIDE or the REPL: both share the block's cache.\<close>

context CB
begin

ML \<open>
local open Cache_Test
  val lthy = \<^context>
  fun noted s =
    let val th = Goal.prove lthy [] [] (Syntax.read_prop lthy s) (fn {context, ...} => simp_tac context 1)
    in #2 (Local_Theory.note ((\<^binding>\<open>ed\<close>, []), [th]) lthy) end
  val (l1, _) = links (noted "f 2 = f 2")
  val (l2, _) = links (noted "f 3 = f 3")
in
  val _ = check_all "a lemma executed again after an edit"
   [("the first execution's link carries its statement", fn () =>
      #statement (#2 (the_link l1 "ed")) = "f 2 = f 2"),
    ("the second execution's link carries the edited statement", fn () =>
      #statement (#2 (the_link l2 "ed")) = "f 3 = f 3")]
end
\<close>

end


section \<open>Local notation of the first caller (D54's accepted deviation)\<close>

locale LS = fixes f :: "nat \<Rightarrow> nat \<Rightarrow> nat"
begin
lemma ls: "f x y = f x y" by (rule refl)
end

locale LT = fixes z :: nat

sublocale LT \<subseteq> s: LS lj .

context LT
begin

lemma True
  including lj_syntax
proof -
  ML_prf \<open>Cache_Test.see "lj_syntax" (#1 (Cache_Test.links \<^context>))\<close>
  show ?thesis ..
qed

lemma True
proof -
  ML_prf \<open>
    local open Cache_Test
      val first = saw "lj_syntax"
      val (later, _) = links \<^context>
      val (fresh_ls, _) = links (fresh \<^theory> "LT")
      fun statement ls = #statement (#2 (the_link ls "ls"))
    in
      val _ = check_all "local notation of the first caller"
       [("the first call, under including lj_syntax, prints \<oplus>", fn () =>
          statement first = "?x \<oplus> ?y = ?x \<oplus> ?y"),
        ("a later proof without it shows the same texts", fn () =>
          map texts later = map texts first),
        ("a fresh lineage prints lj", fn () => statement fresh_ls = "lj ?x ?y = lj ?x ?y"),
        ("the links of both proofs are a fresh lineage's but for the texts", fn () =>
          map untexted first = map untexted fresh_ls andalso
          map untexted later = map untexted fresh_ls)]
    end
  \<close>
  show ?thesis ..
qed

end


section \<open>An interrupted call and a failed print\<close>

text \<open>The print translation of \<open>ct\<close> waits in its first call to be interrupted, or raises
  \<open>Interrupt_Breakdown\<close> once, as running out of stack while printing would.\<close>

definition ct :: "nat \<Rightarrow> nat" where "ct n = n"

ML \<open>
structure Cache_Test_Printing =
struct
  datatype mode = Off | Wait | Break;
  val mode = Synchronized.var \<^unchecked_name>\<open>Cache_Test_Printing.mode\<close> Off;
  (*whether the waiting print has started, and whether it has stopped*)
  val waiting = Synchronized.var \<^unchecked_name>\<open>Cache_Test_Printing.waiting\<close> (false, false);
  fun translation _ _ =
    (case Synchronized.change_result mode (fn m => (m, Off)) of
      Wait =>
        let
          val _ = Synchronized.change waiting (K (true, false));
          val r = Exn.capture Time.sleep (seconds 60.0);
          val _ = Synchronized.change waiting (K (true, true));
        in Exn.release r; raise Match end
    | Break => raise Exn.Interrupt_Breakdown
    | Off => raise Match);
  fun await f =
    let val deadline = Time.now () + seconds 60.0 in
      Synchronized.timed_access waiting (K (SOME deadline))
        (fn st => if f st then SOME ((), st) else NONE)
      |> is_some
    end;
end
\<close>

print_translation \<open>[(\<^const_syntax>\<open>ct\<close>, Cache_Test_Printing.translation)]\<close>

locale CT = fixes f :: "nat \<Rightarrow> nat"
begin
lemma ctl: "f (ct 0) = f (ct 0)" by (rule refl)
end

locale CU = fixes c :: nat

sublocale CU \<subseteq> u: CT Suc .

ML \<open>
local open Cache_Test Cache_Test_Printing
  val thy = \<^theory>
  val ctxt = fresh thy "CU"
  val _ = Synchronized.change waiting (K (false, false))
  val _ = Synchronized.change mode (K Wait)
  val call = Future.fork (fn () => Link_Finder.links ctxt)
  val started = await #1
  val _ = Future.cancel call
  val first = Future.join_result call
  (*the interrupted print has stopped, and its entry has been reset (lazy.ML:113-114)*)
  val stopped = await #2
  val _ = Time.sleep (seconds 1.0)
  val again = Exn.capture (fn () => #1 (links ctxt)) ()
  val (fresh_ls, _) = links (fresh thy "CU")
in
  val _ = check_all "an interrupted call"
   [("is interrupted while printing", fn () =>
      started andalso stopped andalso
      (case first of Exn.Exn exn => Exn.is_interrupt exn | Exn.Res _ => false)),
    ("and leaves the cache usable: the next call gives a fresh lineage's links", fn () =>
      (case again of Exn.Res ls => ls = fresh_ls | Exn.Exn _ => false))]
end
\<close>

ML \<open>
local open Cache_Test Cache_Test_Printing
  val thy = \<^theory>
  val ctxt = fresh thy "CU"
  val _ = Synchronized.change mode (K Break)
  val first = Exn.capture (fn () => Link_Finder.links ctxt) ()
  val again = Exn.capture (fn () => #1 (links ctxt)) ()
  val (fresh_ls, _) = links (fresh thy "CU")
in
  val _ = check_all "a failed print"
   [("fails the call that met it", fn () =>
      (case first of Exn.Exn exn => Exn.is_interrupt_breakdown exn | Exn.Res _ => false)),
    ("and is not served again: the next call gives a fresh lineage's links", fn () =>
      (case again of Exn.Res ls => ls = fresh_ls | Exn.Exn _ => false))]
end
\<close>

text \<open>The links callback itself, called from Python as in production, over the same failed print:
  it answers no links instead of failing (A1, §8 step 5).  The failure is an
  \<open>Interrupt_Breakdown\<close>, so the call also writes an event-log record (D69), and the block refuses
  to run unless ISABELLE_EVENT_LOG_DIR names a scratch directory.\<close>

ML \<open>
local open Cache_Test Cache_Test_Printing
  val _ = Link_Finder_Test.scratch_event_log ()
  val _ = Synchronized.change mode (K Break)
  val answer = Exn.capture (Run_Python.run_with
    [Semantic_Store.make_links_callback (fresh \<^theory> "CU")])
    "return str(len(await connection.callback('Semantic_Store.links', None)))"
  val met = Synchronized.value mode = Off
in
  val _ = check_all "a failed print in the links callback"
   [("the callback's finder meets the failed print", fn () => met),
    ("answers no links instead of failing", fn () =>
      (case answer of Exn.Res (SOME "0") => true | _ => false))]
end
\<close>

end
