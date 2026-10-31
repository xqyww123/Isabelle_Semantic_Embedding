(*
  The entities of the dictionary (LINK_LAYER_PLAN.md §2, §4.5, §7; D40, D51): the
  constants of the context-side terms the dictionary line prints, read after the
  context's uncheck with cases off and abbreviations not contracted, in order of
  first occurrence, each once, those declared in Pure and HOL.HOL left out.  Each
  pin compares (printed name, key) pairs: the key is the constant's identity
  (D34), the printed name the text the entities block embeds (D50).
*)
theory Link_Finder_Entities_Test
  imports Link_Finder_Test_Base
begin

locale EA = fixes f :: "nat \<Rightarrow> nat"
begin
lemma ea: "f x = f x" by (rule refl)
end

definition eg :: "nat \<Rightarrow> nat" where "eg x = x + 1"
abbreviation eh :: "nat \<Rightarrow> nat" where "eh \<equiv> \<lambda>x. eg (eg x)"

text \<open>The dictionary prints \<open>f = eh\<close>; the abbreviation is not contracted for the
  entities, so the block lists \<open>eg\<close>.\<close>

locale EB = fixes b :: nat
sublocale EB \<subseteq> e: EA eh .

text \<open>\<open>If\<close> and \<open>(=)\<close> are declared in \<open>HOL.HOL\<close>; \<open>eg\<close> occurs three times.\<close>

locale EC = fixes c :: nat
sublocale EC \<subseteq> e: EA "\<lambda>x. if x = 0 then eg x else eg (eg x)" .

text \<open>Why abbreviations are not contracted: a locale's own definition applied to its
  parameters would become the local abbreviation \<open>edf\<close>, which has no record.\<close>

locale ED = fixes d :: "nat \<Rightarrow> nat"
begin
definition edf :: "nat \<Rightarrow> nat" where "edf x = d (d x)"
end
sublocale ED \<subseteq> e: EA "ED.edf d" .

text \<open>One constant printed at two types: \<open>ep\<close> at \<open>nat \<Rightarrow> nat\<close> prints as \<open>epn\<close>.\<close>

definition ep :: "'a \<Rightarrow> 'a" where "ep x = x"
abbreviation epn :: "nat \<Rightarrow> nat" where "epn \<equiv> ep"

locale EN = fixes g :: "nat \<Rightarrow> nat" begin lemma en: "g 0 = g 0" by (rule refl) end
locale EI = fixes h :: "int \<Rightarrow> int" begin lemma ei: "h 0 = h 0" by (rule refl) end
locale EP = fixes c :: nat
sublocale EP \<subseteq> n: EN ep .
sublocale EP \<subseteq> i: EI ep .

text \<open>A Level 3 approximate link whose pure rewrites mixin the edge does not carry (D21):
  the mixin is not recovered (D62), so the link carries no rewrite and its entities are the
  instance's alone; the mixin's \<open>(+)\<close> and \<open>0\<close> are not listed.\<close>

locale XM = fixes g :: "nat \<Rightarrow> nat"
begin
definition xf where "xf = (\<lambda>x. g x)"
lemma xfoo: "xf = g" by (simp add: xf_def)
end
locale XK = fixes k :: "nat \<Rightarrow> nat"
sublocale XK \<subseteq> x: XM "\<lambda>n. eg (k n)" rewrites "XM.xf (\<lambda>n. eg (k n)) = (\<lambda>n. eg (k (n + 0)))"
  by (simp add: XM.xf_def)

text \<open>A constant both the instance and a definitional rewrite contain: outside a class context
  \<open>Max\<close>'s rewrite keeps its locale form \<open>linorder.Max (\<le>)\<close>, which shares \<open>(\<le>)\<close> with the
  instance \<open>ord.max (\<le>)\<close>; the link lists it once.\<close>

locale YN = fixes c :: nat
sublocale YN \<subseteq> yo: linorder "(\<le>) :: nat \<Rightarrow> nat \<Rightarrow> bool" "(<)" by unfold_locales auto

text \<open>D65: a link's rewrites are the definitional equations Level 3 exact's pre-check applied.
  Two equations overlap: \<open>s_def\<close>'s definiens \<open>Suc p\<close> lies inside \<open>t_def\<close>'s \<open>Suc (Suc p)\<close>.
  Bottom-up rewriting fires \<open>s_def\<close> first, so \<open>t_def\<close> never fires, although its definiens
  occurs in the template and not in the fact and its folded \<open>t\<close> occurs in the fact.\<close>

locale OT = fixes a :: nat and b :: nat
begin
lemma ot: "a = a \<and> b = b" by simp
end

locale OV = fixes p :: nat
begin
definition s :: nat where "s = Suc p"
definition t :: nat where "t = Suc (Suc p)"
sublocale ov: OT "Suc (Suc p)" t rewrites "Suc p = s" by (simp add: s_def)
end

ML \<open>
local open Link_Finder_Test
  val thy = \<^theory>
  fun ctxt_of loc = Named_Target.init [] (Locale.check_global thy (loc, Position.none)) thy
  (*the distinct entity lists of the links from S whose note satisfies the test*)
  fun entities ctxt S note =
    Link_Finder.links ctxt |> map #2
    |> filter (fn l: Link_Finder.link => #source l = S andalso note (#note l))
    |> map #entities |> distinct (op =)
  fun pairs ctxt nks =
    map (fn (n, c) => (n, Universal_Key.key_of NONE (Context.Proof ctxt) (Universal_Key.Constant c))) nks
  fun is n (m, _) = m = n
  (*D65: the head constants of the folded terms of the equations Level 3 exact applied*)
  fun folded_heads (Link_Finder.Level3_Exact eqs) = map (#1 o dest_Const o head_of o #2) eqs
    | folded_heads _ = []
  val T = "Link_Finder_Entities_Test."
  val linorder = ctxt_of "linorder" and comm_monoid_add = ctxt_of "comm_monoid_add"
  val order = ctxt_of "order" and semilattice_inf = ctxt_of "semilattice_inf"
in
  val _ = check_all "entities"
   [("linorder: Max.insert lists max, then Max", fn () =>
      member (op =) (entities linorder "Lattices_Big.semilattice_set" (is "insert"))
        (pairs linorder [("max", "Orderings.ord_class.max"), ("Max", "Lattices_Big.linorder_class.Max")])),
    ("comm_monoid_add: sum.distrib lists (+), 0 and sum in that order", fn () =>
      entities comm_monoid_add "Groups_Big.comm_monoid_set" (is "distrib") =
        [pairs comm_monoid_add
          [("(+)", "Groups.plus_class.plus"), ("0", "Groups.zero_class.zero"),
           ("sum", "Groups_Big.comm_monoid_add_class.sum")]]),
    ("order: the dual order's links list (\<le>) and (<), the identity's none", fn () =>
      eq_set (op =) (entities order "Orderings.ordering" (K true),
        [pairs order [("(\<le>)", "Orderings.ord_class.less_eq"), ("(<)", "Orderings.ord_class.less")], []])),
    ("linorder: every identity link without rewrites has an empty list", fn () =>
      Link_Finder.links linorder |> map #2
      |> filter (fn l => kind l = Link_Finder.Identity andalso null (#rewrites l))
      |> (fn ls => not (null ls) andalso forall (null o #entities) ls)),
    ("semilattice_inf: the renaming tier lists the Renamed f only, as (\<sqinter>)", fn () =>
      entities semilattice_inf "Lattices.semilattice_order" (K true) =
        [pairs semilattice_inf [("(\<sqinter>)", "Lattices.inf_class.inf")]]),
    ("EB: an abbreviation is not contracted, eh lists eg", fn () =>
      let val c = ctxt_of "EB" in entities c (T ^ "EA") (is "ea") = [pairs c [("eg", T ^ "eg")]] end),
    ("EC: HOL.HOL's If and (=) are left out, eg is listed once after 0", fn () =>
      let val c = ctxt_of "EC"
      in entities c (T ^ "EA") (is "ea") = [pairs c [("0", "Groups.zero_class.zero"), ("eg", T ^ "eg")]] end),
    ("ED: a locale's own definition is listed as itself, not as its local abbreviation", fn () =>
      let val c = ctxt_of "ED" in entities c (T ^ "EA") (is "ea") = [pairs c [("ED.edf", T ^ "ED.edf")]] end),
    ("EP: one constant at two types, each printed name its own link's", fn () =>
      let val c = ctxt_of "EP" in
        entities c (T ^ "EN") (K true) = [pairs c [("epn", T ^ "ep")]] andalso
        entities c (T ^ "EI") (K true) = [pairs c [("ep", T ^ "ep")]]
      end),
    ("collect_constants, the one fold: each kept constant once, in order of first occurrence", fn () =>
      let
        val c = ctxt_of "EC"
        val t = Syntax.read_term c "\<lambda>x. if x = 0 then eg x else eg (eg x)"
      in
        map (#1 o dest_Const o #1) (Explain_Term.collect_constants (K true) (Context.Proof c) [t, t]) =
          ["HOL.If", "HOL.eq", "Groups.zero_class.zero", T ^ "eg"]
      end),
    ("YN: a constant of both the instance and a definitional rewrite is listed once", fn () =>
      let val c = ctxt_of "YN" in
        member (op =) (entities c "Lattices_Big.semilattice_set" (is "closed"))
          (pairs c [("ord.max", "Orderings.ord.max"), ("(\<le>)", "Orderings.ord_class.less_eq"),
            ("linorder.Max", "Lattices_Big.linorder.Max")])
      end),
    ("XK: a pure rewrites mixin gives no rewrite and no entity (D62)", fn () =>
      let
        val c = ctxt_of "XK"
        val ls = Link_Finder.links c |> map #2
          |> filter (fn l: Link_Finder.link => #source l = T ^ "XM" andalso #note l = ("xfoo", 0))
      in
        not (null ls) andalso
        forall (fn l => #level l = Link_Finder.Level3_Approximate andalso null (#rewrites l) andalso
          #entities l = pairs c [("eg", T ^ "eg")]) ls
      end),
    ("comm_monoid_add: sum_def, a Level 2 link, carries no rewrite and no entity (D65)", fn () =>
      let
        val ls = Link_Finder.links comm_monoid_add |> map #2
          |> filter (fn l: Link_Finder.link => #source l = "Groups.comm_monoid_add" andalso
               #note l = ("sum_def", 0))
      in
        not (null ls) andalso
        forall (fn l => #level l = Link_Finder.Level2 andalso null (#rewrites l) andalso
          null (#entities l)) ls
      end),
    ("comm_monoid_add: sum.distrib, a Level 3 exact link, carries the sum rewrite (D65)", fn () =>
      let
        val ls = Link_Finder.links comm_monoid_add |> map #2
          |> filter (fn l: Link_Finder.link => #source l = "Groups_Big.comm_monoid_set" andalso
               #note l = ("distrib", 0))
      in
        not (null ls) andalso
        forall (fn l => folded_heads (#level l) = ["Groups_Big.comm_monoid_add.sum"]) ls
      end),
    ("linorder: sorted_key_list_of_set_empty carries the sorted_list_of_set rewrite and entity (D65)",
      fn () =>
      let
        val ls = Link_Finder.links linorder |> map #2
          |> filter (fn l: Link_Finder.link => #source l = "List.folding_insort_key" andalso
               #note l = ("sorted_key_list_of_set_empty", 0))
        val sorted = #2 (hd (pairs linorder [("", "List.linorder_class.sorted_list_of_set")]))
      in
        not (null ls) andalso
        forall (fn l => folded_heads (#level l) = ["List.linorder.sorted_list_of_set"] andalso
          member (op =) (map #2 (#entities l)) sorted) ls
      end),
    ("OV: of two overlapping equations only the one that fired is a rewrite (D65)", fn () =>
      let
        val ls = Link_Finder.links (ctxt_of "OV") |> map #2
          |> filter (fn l: Link_Finder.link => #source l = T ^ "OT" andalso #note l = ("ot", 0))
      in
        not (null ls) andalso
        forall (fn l => folded_heads (#level l) = [T ^ "OV.s"] andalso length (#rewrites l) = 1) ls
      end)]
end
\<close>

end
