// isabelle_vector-inl.h - Highway SIMD implementation for Q15 dot product
#include <stdint.h>
#include <stddef.h>
#include "hwy/highway.h"

HWY_BEFORE_NAMESPACE();
namespace project {
namespace HWY_NAMESPACE {

namespace hwy = ::hwy::HWY_NAMESPACE;

// 两个操作数一律用 LoadU(非对齐 load)。原因:候选向量指针直接指向 LMDB mmap 里的
// value,其地址恒为 page_base+16(overflow page 头 16B),不是 32/64B 对齐;而实测
// LoadU 与对齐 Load 同速(75.5ms vs 76.0ms,4% 噪声内),故不值得为对齐做 memcpy 或
// padding。用 LoadU 后本 kernel 对任意对齐的输入都安全。
//
// 乘法用 MulFixedPoint15 = round((a*b) / 32768)(x86: 单条 VPMULHRSW),而不是
// MulHigh = floor((a*b) / 65536)。MulHigh 的向下取整对每一项都产生同号的 [0,1) 残差,
// 累加后系统性压低结果;更糟的是残差均值随两向量的相关度变化(近正交时 ~0.5,高度相关
// 时远小于 0.5),所以任何常数校正都会在 cos→1 处过冲(实测 +0.023,并恢复出 >1 的假
// cos)。舍入乘无偏,误差降约 10 倍,且实测吞吐完全相同(25.8ms vs 25.7ms)。
//
// 标度:每项表示 a_i*b_i,单位 1/32768(Q1.15),故整段和 s = 32768 * norm^2 * cos。
// 向量按 L2 范数 0.95 归一 => |s| <= 32768*0.9025 ~= 29573 < 32767,int16 累加器有
// 1.11x 余量;Cauchy-Schwarz 保证任意维度子集的部分和(含 per-lane 与 ReduceSum 的
// 中间值)受同一上界约束(实测 per-lane 峰值仅 ~1.6k)。
int16_t DotQ15Impl(const int16_t* a, const int16_t* b, size_t N) {
  const hwy::ScalableTag<int16_t> d16;

  const size_t L = hwy::Lanes(d16);
  auto vacc = hwy::Zero(d16);  // int16 累加器

  size_t i = 0;
  for (; i + L <= N; i += L) {
    auto va16 = hwy::LoadU(d16, a + i);
    auto vb16 = hwy::LoadU(d16, b + i);
    auto prod16 = hwy::MulFixedPoint15(va16, vb16);
    vacc = hwy::Add(vacc, prod16);
  }

  // 剩余部分用 MaskedLoad
  const size_t remaining = N - i;
  if (remaining) {
    auto m = hwy::FirstN(d16, remaining);
    auto va16 = hwy::MaskedLoad(m, d16, a + i);
    auto vb16 = hwy::MaskedLoad(m, d16, b + i);
    auto prod16 = hwy::MulFixedPoint15(va16, vb16);
    vacc = hwy::Add(vacc, prod16);
  }
  return hwy::ReduceSum(d16, vacc);
}

}  // namespace HWY_NAMESPACE
}  // namespace project
HWY_AFTER_NAMESPACE();

