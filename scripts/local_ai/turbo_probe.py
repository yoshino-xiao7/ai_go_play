"""Exercise the CUDA kernels needed by the shipped H3 Turbo workflow."""
import torch
from sageattention.core import get_cuda_arch_versions, per_thread_int8_triton, per_warp_int8_cuda, per_block_int8_triton, per_channel_fp8, attn_false
from sageattention import sageattn
import comfy_kitchen

assert torch.cuda.is_available(), 'NVIDIA CUDA GPU unavailable'
assert get_cuda_arch_versions(), 'SageAttention CUDA architecture unavailable'
assert hasattr(comfy_kitchen, 'sol_attn'), 'ComfyUI comfy-kitchen lacks sol_attn'
q = torch.randn(1, 4, 256, 128, device='cuda', dtype=torch.bfloat16)
y = sageattn(q, q, q, tensor_layout='HND', is_causal=False)
# KJ's memory-efficient path on RTX 30/40 also JIT-compiles Triton kernels.
per_thread_int8_triton(q, q, tensor_layout='HND')
torch.cuda.synchronize()
assert y.shape == q.shape and bool(torch.isfinite(y).all()), 'SageAttention kernel validation failed'
print('H3 Turbo CUDA kernels OK')
