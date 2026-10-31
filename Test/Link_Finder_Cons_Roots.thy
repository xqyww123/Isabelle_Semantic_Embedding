(*
  Link finder cases with root registrations (LINK_LAYER_PLAN.md §4.3, §7): nodes
  keyed by their root registration (M06), the registration predicate (D52), the
  Level 0 split ahead of it and of Level 5 (M05), and a root registration whose
  own table holds a schematic variable, of a term or of a type (B19).
*)
theory Link_Finder_Cons_Roots
  imports Link_Finder_Test_Base
begin

ML \<open>
structure Link_Finder_Roots_Test =
struct

open Link_Finder_Test

(*the element's line and the report's recognised facts and Level 5 base names*)
fun run ctxt label name =
  let val (_, r) = report_in ctxt label
  in (element_string ctxt (the_element (#elements r) name 0), #recognised r, #level5_base_names r, r) end;

end
\<close>

section \<open>An in-block sublocale whose rewrites mixin changes a statement (M06)\<close>

text \<open>The sublocale brings an edge and a root registration to one (source, chain, instance).
  Keyed by its root, the root's node reads its propositions through the registration's
  morphism, mixin included, so \<open>s.kfoo\<close> (\<open>k 0 = k 0\<close> after the mixin) links at Level 2.
  Without a root, as in \<open>Locale.init\<close> of \<open>KL\<close>, the edge carries no mixin (D21) and the link
  is approximate.\<close>

locale KM = fixes g :: "nat \<Rightarrow> nat"
begin
definition kh where "kh x = g x"
lemma kfoo: "kh 0 = g 0" by (simp add: kh_def)
end

locale KL = fixes k :: "nat \<Rightarrow> nat"

context KL
begin

sublocale s: KM k rewrites "KM.kh k = k" by (rule ext) (simp add: KM.kh_def)

ML \<open>
local open Link_Finder_Roots_Test
  val (line, recognised, _, r) = run \<^context> "root key" "local.s.kfoo"
in
  val _ = check ("root key: " ^ line) (line = "local.s.kfoo#0: Level 2 KM::kfoo#3 @[s] [k]")
  val _ = check "root key: the edge and the root give two nodes below the bottom" (#nodes r = 3)
  val _ = check "root key: the sublocale wrote s.kfoo" (member (op =) recognised "local.s.kfoo")
end
\<close>

end

ML \<open>
local open Link_Finder_Roots_Test
  val (ctxt, _, r) = report \<^theory> "KL"
in
  val _ = check_element ctxt "Locale.init KL" (#elements r) "local.s.kfoo" 0
    "local.s.kfoo#0: Level 3 approximate KM::kfoo#3 @[s] [k]"
end
\<close>

section \<open>The registration predicate (D52)\<close>

text \<open>An unqualified proof interpret of \<open>RA\<close> writes \<open>refl\<close> over the edge-reached \<open>RB.refl\<close>, at the
  command's position, with the same statement \<open>s ?x ?x\<close>.  The fact is recognised, and the
  narrowing leaves only the name hits under the root registration, so it links to its writer
  \<open>RA.refl\<close>; without the narrowing, \<open>RB.refl\<close>, first in the order of trial (its instance
  \<open>[s]\<close> is the smaller), would pass Level 2 as well.\<close>

locale RB = fixes s :: "'a \<Rightarrow> 'a \<Rightarrow> bool" assumes refl: "s x x"
locale RA = fixes r :: "'a \<Rightarrow> 'a \<Rightarrow> bool" assumes refl: "r x x"
locale RC = RB

context RC
begin

lemma True
proof -
  interpret RA "\<lambda>x y. s y x" by unfold_locales (rule refl)
  ML_val \<open>
    local open Link_Finder_Roots_Test
      val (line, recognised, _, _) = run \<^context> "interpret over an edge-reached name" "local.refl"
    in
      val _ = check ("interpret over an edge-reached name: " ^ line)
        (line = "local.refl#0: Level 2 RA::refl#1 @[] [\<lambda>x y. s y x]")
      val _ = check "interpret over an edge-reached name: refl is recognised"
        (member (op =) recognised "local.refl")
    end
  \<close>
  show ?thesis ..
qed

end

text \<open>Two unqualified interprets of one locale: the second wrote \<open>fd\<close>; the order of trial puts
  the first's smaller instance first, and Level 2 chooses the second.\<close>

locale RD = fixes f :: "nat \<Rightarrow> nat" assumes fd: "f 0 = f 0"

lemma True
proof -
  interpret RD Suc by unfold_locales (rule refl)
  interpret RD "\<lambda>x. Suc (Suc x)" by unfold_locales (rule refl)
  ML_val \<open>
    local open Link_Finder_Roots_Test
      val (line, _, _, r) = run \<^context> "two interprets" "local.fd"
    in
      val _ = check ("two interprets: " ^ line)
        (line = "local.fd#0: Level 2 RD::fd#1 @[] [\<lambda>x. Suc (Suc x)]")
      val _ = check "two interprets: two root registrations" (#roots r = 2)
    end
  \<close>
  show ?thesis ..
qed

section \<open>Level 0 runs first (M05)\<close>

text \<open>A name the proof stated reaches neither the registration predicate nor Level 5: here
  \<open>antisym\<close> has name hits away from its position and would otherwise be recognised.  \<open>this\<close>,
  \<open>that\<close>, \<open>assms\<close> and \<open>prems\<close> carry no name hint of their own, pass Level 0 and reach Level 5,
  which finds no locale noting them.\<close>

context order
begin

lemma "x \<le> x"
proof -
  have antisym: "x \<le> x" by simp
  ML_val \<open>
    local open Link_Finder_Roots_Test
      val (line, recognised, level5, _) = run \<^context> "Level 0, have" "local.antisym"
    in
      val _ = check ("Level 0, have: " ^ line) (line = "local.antisym#0: Level 0")
      val _ = check "Level 0, have: antisym is neither recognised nor looked up by Level 5"
        (not (member (op =) recognised "local.antisym") andalso not (member (op =) level5 "antisym"))
      val _ = check "Level 0, have: no fact is recognised" (null recognised)
    end
  \<close>
  show ?thesis by (rule antisym)
qed

end

lemma
  assumes antisym: "(x::nat) \<le> y"
  shows "x \<le> y"
proof -
  ML_val \<open>
    local open Link_Finder_Roots_Test
      val (line, _, level5, _) = run \<^context> "Level 0, assumes" "local.antisym"
    in
      val _ = check ("Level 0, assumes: " ^ line) (line = "local.antisym#0: Level 0")
      val _ = check "Level 0, assumes: Level 5 does not look antisym up"
        (not (member (op =) level5 "antisym"))
    end
  \<close>
  show ?thesis by (rule antisym)
qed

section \<open>A root registration whose own table holds a schematic variable (B19)\<close>

text \<open>A proof interpret with a \<open>for\<close> variable is a root registration whose own table holds a
  schematic variable; the edges below it may hold their own, of the same name.  Isabelle's facts
  keep them apart, and so must the nodes' instances: the argument's schematic variables are raised
  above the root's own table before it is substituted, by one offset for every argument.
  \<^item> \<open>p\<close>: one parameter, a term variable: the instance keeps two schematic variables.
  \<^item> \<open>q\<close>: the same with a type variable: two schematic variables and no free variable of the
    root's locale.
  \<^item> \<open>r\<close>: two parameters, \<open>c\<close> receiving the root's and the edge's variable and \<open>a\<close> only the
    root's: two schematic variables, the root's with one index in both.
  \<^item> \<open>s\<close>: two parameters, \<open>a\<close> receiving the root's variable and \<open>c\<close> the edge's, both named
    \<open>x4\<close>: two distinct variables, so both parameters are renamed and the link is a renaming
    (merged, two parameters would receive one variable, A2, and the link would be proper).
  Each construction has its own variable name, the same in its edge and its root, so that the
  four interprets in one proof do not rename each other's variables; they are checked together,
  so that one mutant run shows every pin it fails.\<close>

locale B19A = fixes a :: "nat \<Rightarrow> nat" assumes ax: "a 0 = a 0"
locale B19B = fixes b :: "nat \<Rightarrow> nat"
sublocale B19B \<subseteq> e: B19A "\<lambda>y. b (x1 y)" for x1 :: "nat \<Rightarrow> nat" by unfold_locales (rule refl)

locale B19A' = fixes a :: "'a \<Rightarrow> 'a" assumes ax: "a x = a x"
locale B19B' = fixes b :: "'a \<Rightarrow> 'a"
sublocale B19B' \<subseteq> e: B19A' "\<lambda>y. b (x2 y)" for x2 :: "'a \<Rightarrow> 'a" by unfold_locales (rule refl)

locale B19C = fixes a c :: "nat \<Rightarrow> nat" assumes ax: "a 0 = a 0"
locale B19D = fixes b :: "nat \<Rightarrow> nat"
sublocale B19D \<subseteq> e: B19C b "\<lambda>y. b (x3 y)" for x3 :: "nat \<Rightarrow> nat" by unfold_locales (rule refl)
locale B19E = fixes b :: "nat \<Rightarrow> nat"
sublocale B19E \<subseteq> e: B19C b x4 for x4 :: "nat \<Rightarrow> nat" by unfold_locales (rule refl)

lemma True
proof -
  interpret p: B19B "\<lambda>y. x1 (Suc y)" for x1 :: "nat \<Rightarrow> nat" .
  interpret q: B19B' "\<lambda>y. x2 (x2 y)" for x2 :: "'b \<Rightarrow> 'b" .
  interpret r: B19D "\<lambda>y. z3 (Suc y)" for z3 :: "nat \<Rightarrow> nat" .
  interpret s: B19E x4 for x4 :: "nat \<Rightarrow> nat" .
  ML_val \<open>
    local open Link_Finder_Roots_Test
      val ctxt = \<^context>
      val (F, r) = report_in ctxt "B19"
      fun element name = the_element (#elements r) name 0
      fun line name = element_string ctxt (element name)
      fun instance name = #instance (the (#template (element name)))
      fun vars name = length (fold Term.add_vars (instance name) [])
      fun level2 name prefix = String.isPrefix (name ^ "#0: Level 2 " ^ prefix) (line name)
      val R = Link_Finder.Renamed
      val s_key =
        Universal_Key.key_of_theorem' NONE (Context.Proof ctxt) (Proof_Context.get_thm ctxt "s.e.ax")
    in
      val _ = check_all "B19"
       [("p: Level 2", fn () => level2 "local.p.e.ax" "B19A::ax#1 @[p.e]"),
        ("p: two schematic variables", fn () => vars "local.p.e.ax" = 2),
        ("q: Level 2", fn () => level2 "local.q.e.ax" "B19A'::ax#1 @[q.e]"),
        ("q: two schematic variables", fn () => vars "local.q.e.ax" = 2),
        ("q: no free variable", fn () => null (fold Term.add_frees (instance "local.q.e.ax") [])),
        ("r: Level 2", fn () => level2 "local.r.e.ax" "B19C::ax#1 @[r.e]"),
        ("r: two schematic variables", fn () => vars "local.r.e.ax" = 2),
        ("s: Level 2", fn () => level2 "local.s.e.ax" "B19C::ax#1 @[s.e]"),
        ("s: two schematic variables", fn () => vars "local.s.e.ax" = 2),
        ("s: a renaming, both parameters renamed", fn () =>
          (case AList.lookup (op =) (Link_Finder.links_of F) s_key of
            SOME l => kind l = Link_Finder.Renaming andalso map #verdict (#params l) = [R, R]
          | NONE => false))]
    end
  \<close>
  show ?thesis ..
qed

end
