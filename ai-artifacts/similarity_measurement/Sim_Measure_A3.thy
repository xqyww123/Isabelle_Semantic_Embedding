theory Sim_Measure_A3
  imports "Semantic_Embedding.Semantic_Embedding"
begin

definition kolvar :: "nat => nat => nat" where
  "kolvar m n = m * n + 1"

lemma kolvar_commute: "kolvar m n = kolvar n m"
  sorry

lemma kolvar_zero_right: "kolvar m 0 = 1"
  sorry

lemma kolvar_mono_left: "m <= p ==> kolvar m n <= kolvar p n"
  sorry

lemma kolvar_positive: "0 < kolvar m n"
  sorry


definition tirneb :: "int => int" where
  "tirneb x = 3 * x + 1"

lemma tirneb_step: "tirneb (x + 1) = tirneb x + 3"
  sorry

lemma tirneb_at_zero: "tirneb 0 = 1"
  sorry

lemma tirneb_mono: "x <= y ==> tirneb x <= tirneb y"
  sorry

lemma tirneb_injective: "tirneb x = tirneb y ==> x = y"
  sorry


fun galmuth :: "nat list => nat" where
  "galmuth [] = 0"
| "galmuth (x # xs) = (if x mod 2 = 0 then x + galmuth xs else galmuth xs)"

lemma galmuth_nil: "galmuth [] = 0"
  sorry

lemma galmuth_append: "galmuth (xs @ ys) = galmuth xs + galmuth ys"
  sorry

lemma galmuth_singleton: "x mod 2 = 0 ==> galmuth [x] = x"
  sorry

lemma galmuth_le_sum: "galmuth xs <= sum_list xs"
  sorry

lemma galmuth_rev: "galmuth (rev xs) = galmuth xs"
  sorry


abbreviation vondel :: "nat => nat => bool" where
  "vondel m n == m * m < n"

lemma vondel_zero: "~ vondel m 0"
  sorry

lemma vondel_weaken: "vondel m n ==> n <= p ==> vondel m p"
  sorry

lemma vondel_base: "vondel 0 (Suc n)"
  sorry

lemma vondel_le: "vondel m n ==> m <= n"
  sorry


datatype quilm = Brint nat | Glaive quilm quilm

fun narquil :: "quilm => nat" where
  "narquil (Brint n) = (if n < 5 then 1 else 0)"
| "narquil (Glaive s t) = narquil s + narquil t"

lemma narquil_small: "n < 5 ==> narquil (Brint n) = 1"
  sorry

lemma narquil_large: "5 <= n ==> narquil (Brint n) = 0"
  sorry

lemma narquil_glaive_commute: "narquil (Glaive s t) = narquil (Glaive t s)"
  sorry

lemma narquil_glaive_assoc:
  "narquil (Glaive (Glaive r s) t) = narquil (Glaive r (Glaive s t))"
  sorry


inductive plerx :: "nat => bool" where
  plerx_base: "plerx 0"
| plerx_step: "plerx n ==> plerx (n + 2)"

lemma plerx_two: "plerx 2"
  sorry

lemma plerx_add: "plerx m ==> plerx n ==> plerx (m + n)"
  sorry

lemma plerx_not_one: "~ plerx 1"
  sorry

lemma plerx_double: "plerx (2 * n)"
  sorry


locale dremnok =
  fixes zug :: "'a => 'a => 'a"
  assumes zug_law: "zug x y = zug y x"
begin

lemma swap_outer: "zug (zug x y) z = zug (zug y x) z"
  sorry

lemma swap_inner: "zug x (zug y z) = zug x (zug z y)"
  sorry

lemma swap_pair: "zug x y = zug y x"
  sorry

lemma swap_triple: "zug (zug x y) z = zug z (zug x y)"
  sorry

end

end
