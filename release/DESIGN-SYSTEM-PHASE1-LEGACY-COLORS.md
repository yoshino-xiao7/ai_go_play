# 设计系统阶段 1：清理可见旧色系（2026-11-19）

本页是带日期的执行记录，规范见 [Design System](../docs/design-system/README.md)、[Token 参考](../docs/design-system/TOKENS.md) 和 [样式债务](../docs/design-system/STYLE-DEBT.md) D3。

## 范围

批准范围是按顺序逐个文件，清理 ComfyUI、角色管理和画布自动编排中仍可见的旧绿色和旧冷蓝色，对应 `frontend/src/comfy.css`、`subjects.css`、`canvas-runs.css`。

- 不修改业务逻辑、交互、真实数据，也不涉及其他设计领域。
- 不新增 Token，只使用 `tokens.css` 中已有的语义 Token。
- 分支：`codex/design-system-phase0`，起点是 `9b5cc6e`。只在本地提交，未推送，未合并。

## 变更

| 提交 | 文件 | 规则 / 字面量 | 实际可见的变化 |
| --- | --- | --- | --- |
| `aa33f11` | `comfy.css` | 46 / 70 | 输入框占位文字由绿色变为暖色次要文字；「等待配置」状态标签和圆点由绿色变为中性。其余规则被 `management.css` 覆盖，替换后渲染结果不变 |
| `81bb9db` | `subjects.css` | 42 / 65 | 主体库、主体编辑、保存到主体库三处界面的冷蓝灰改为暖色；选中的主体类型和按下的筛选项由绿色改为强调色（选中语义）；叠加在用户图片上的半透明层保持原有透明度 |
| `b396ef1` | `canvas-runs.css` | 14 / 18 | 画布自动编排面板整体由冷蓝灰改为暖色；步骤链接改为强调色；成功或复用步骤的描边改为成功色的混合 |

字面量按用途映射，各自对应的 Token：

| 用途 | Token |
| --- | --- |
| 表面 | `surface-panel`、`surface-raised`、`surface-hover`、`surface-sunken`、`surface-chrome`；图片衬底用 `bg-canvas` |
| 描边 | `border`、`border-strong` |
| 文字 | `text`、`text-muted` |
| 选中 | `accent-line`、`accent-soft` |
| 文字链接 | `accent` |
| 成功反馈 | `success` |

以下颜色不属于旧色系，本批不改：

- 危险与失败：失败或阻塞步骤的红色描边、错误文字、缺失徽标、删除悬停色；
- 过渡状态：ComfyUI「启动中」「停止中」的琥珀色。

用户素材的颜色同样不受影响。

## 验证方法

- 数据：隔离端口；冻结的黄金数据，含 5 个项目和合成素材（扁平插画、6 秒视频、两段音频）、剧本与 4 轨时间线。不接触生产素材库，不使用凭据。
- 状态：共 49 个，每个采集 1920×1080 与 1440×900 两种视口。本批新增的状态：

| 状态 | 内容 |
| --- | --- |
| `comfy-logs` | ComfyUI 运行日志 |
| `comfy-input-focus` | ComfyUI 输入框的键盘焦点 |
| `subject-editor` | 从主体卡片「管理主体参考图」打开主体编辑 |
| `subject-save-dialog` | 右键图片 →「保存到主体库」 |
| `subject-library-empty` | 空的主体库 |
| `subject-library-filled` | 通过真实界面保存一个主体后的主体库（使用独立数据副本） |
| `canvas-run` | 自动编排初始面板 |
| `canvas-run-plan` | 在黄金数据「生成测试 1440」上检查计划。计划接口只读，不写数据 |

- 对比方式：每个文件修改前后，都用同一数据和同一脚本完整采集 98 张截图，逐元素比较计算样式，像素按通道取最大差值，超过 24 计为变化。允许发生变化的元素，只能位于该文件对应的界面内。
- 确定性：新增的状态各采集两次，16/16 一致。
- 遮罩：加载转圈（`.spin`）、`progress`、设置页的磁盘剩余空间（`.storage-stats`）与资料库路径（`.path-box`）；`<video>` 元素和插入光标在采集时隐藏。
- 夹具：沿用上一批的 `fixture-comfy-log-focus`，因为日志 `<pre>` 只在真实 ComfyUI 输出日志后才出现。本批新增的状态都是真实界面。

## 结果

| 文件 | 有变化的状态 | 非预期的元素变化 | 该界面内剩余的旧色 |
| --- | --- | --- | --- |
| `comfy.css`（a0 → a1） | 仅 ComfyUI 面板内 | 0 | 2 处，来自其他文件：`management.css` 次要按钮描边、`styles.css` 关闭按钮 |
| `subjects.css`（a1 → a2） | 仅主体库、主体编辑、保存对话框内 | 0 | 5 处，来自 `styles.css`、`canvas.css` |
| `canvas-runs.css`（a2 → a3） | 仅自动编排面板内 | 0 | 0 |

每个文件提交前都执行了 `npm run build`（含 `tsc -b`），结果通过；`node --test tests/governance.test.cjs` 14/14 通过。

## 未覆盖

- 只有在真实 ComfyUI 运行、或有扫描结果时才会出现的界面，没有渲染出来：安装候选列表的选中与悬停、表单保存反馈、运行中的状态。这些规则已经按用途改为 Token，但没有截图证据。
- 其他文件中的旧色仍然可见，列在样式债务 D3 中。
- 只在 Windows 的无头 Edge 中验证。
