# 样式债务

阶段 0 只做治理，界面保持不变。本页列出已经确认、但尚未处理的样式问题，以及证据来源。截图证据来自 2026-11-19 在隔离实例上采集的视觉基线（1920×1080、1440×900），存放在仓库外。处理方式见 [迁移方案](MIGRATION.md)。

## 样式债（属于 Design System 范围）

| 编号 | 问题 | 证据 | 建议阶段 |
| --- | --- | --- | --- |
| D1 | 状态色分散。**阶段 1 已部分处理**：危险、警告、信息 Token 已接入到可实测的界面（见 [阶段 1 记录](../../release/DESIGN-SYSTEM-PHASE1-STATUS.md)）。仍未接入：账号弹层的危险项（`.popover-action-btn.is-danger`，需要绑定账号才能渲染），以及约 15 处无法在隔离环境渲染的错误文字（`production-error`、`timeline-banner.error`、`canvas-run-error`、`subject-error`、`save-canvas-error`、`voice-design-error`、`exit-application-error` 等）；`.generation-job.unknown` 仍为琥珀字面量 | 剩余选择器列表见阶段 1 记录 | 1 |
| D1a | `.video-notice` 一个类同时用于阻塞提示、旧配置提示、待确认提交和后期任务错误，目前统一按警告显示；区分它们需要修改标记 | `VideoComposer.tsx`、`VideoEnhanceComposer.tsx`、`AudioComposer.tsx` | 1 |
| D2 | ~~禁用的主按钮仍是填充的主按钮外观~~。**阶段 1 已处理**（`design/states.css`） | 安装向导「下一步」、ComfyUI「启动服务」、剧本「保存剧本」等 | 已完成 |
| D3 | 旧绿色、旧冷蓝色仍然可见。**阶段 1 已处理 3 个文件**：`comfy.css`、`subjects.css`、`canvas-runs.css`，见 [旧色系记录](../../release/DESIGN-SYSTEM-PHASE1-LEGACY-COLORS.md)。<br>仍可见、来自其他文件：<br>• `management.css`：ComfyUI 次要按钮描边 `#48454f`<br>• `styles.css`：弹窗关闭按钮 `.icon-button`、`.modal-footer` 描边<br>• `canvas.css`：素材面板搜索框、音频缩略图、属性面板输入框、「打开素材预览」按钮<br>• `subject-node.css`：画布上主体卡片的冷色文字和图标<br>• 选中连线的端点、图片大图预览 | 画布素材面板的音频缩略图、属性面板输入框、「打开素材预览」按钮、选中连线的端点、图片大图预览 | 1 |
| D4 | **更正并已处理（阶段 1）**。阶段 0 记录为「焦点色有 3 种」，这一判断对按钮不成立：全局规则用 `!important` 统一了 `button`、`a`、`input`、`select`、`textarea` 的焦点色，蓝色字面量从未生效。真正生效的例外是这条全局规则以外的元素：创作区的 `<summary>`（`#83c4ff`）、ComfyUI 日志（`#7b9c60`）、安装向导路径行（`#ca91a7`）。现在三者都使用 `--color-focus` | 渲染实测 | 已完成 |
| D5 | 字号过小：~~时间线有 77 处可见文字小于 11px；画布状态栏 9px~~；画布状态栏对比度 3.0:1；字重 450 / 550 / 630 / 650 在中文字体下没有效果；声明的 `Inter` 字体从未加载；等宽字体有 4 套写法。**阶段 1 已处理时间线与画布状态栏的字号**，见 [字号记录](../../release/DESIGN-SYSTEM-PHASE1-TYPOGRAPHY.md)。实测时间线中小于 11px 的文字由 72 处降为 0，状态栏由 9px 改为 12px。<br>仍未处理：<br>• 状态栏颜色与对比度（本批不改颜色）<br>• 窄视口（≤ 1100 / ≤ 900px）下时间线仍有 8–10px 规则<br>• `timeline.css` 中按钮、输入框的字号声明被 `.canvas-workspace button, input, textarea { font: inherit }` 覆盖，实际不生效<br>• 画布缩放读数 10px<br>• 其他页面、画布节点内文字、字重、`Inter`、等宽字体 | 渲染实测（`metrics.json`） | 1 |
| D6 | ~~层级排序：提示消息（200）低于视频查看器（1500）和图片查看器（5000），查看器打开时提示会被遮住；自动编排遮罩（属于模态）与右键菜单、选择横幅、视频参数弹层共用 1800~~。**阶段 1 已修正**：提示提到最上层（5100），本体可以点穿；自动编排遮罩改用 `--z-canvas-modal`（1850），见 [层级记录](../../release/DESIGN-SYSTEM-PHASE1-LAYERING.md)。<br>仍未处理（属于交互，不是层级问题）：<br>• 自动编排面板没有限制焦点，Tab 会移到背后的画布，键盘可以在背后打开右键菜单（现在被遮罩挡住）<br>• Esc 不关闭自动编排；选取模式进行中时，第一次 Esc 会取消被遮住的选取 | `tokens.css` 的 `--z-*` 层级 | 1 |
| D7 | 206 处 `!important`、41 个重复定义的顶层选择器（`canvas.css` ~~31 个~~ → 23 个）。**阶段 1 已处理 `canvas.css`**：删除 94 个始终被覆盖的声明，合并 8 组，构建产物逐字节不变，见 [重复定义记录](../../release/DESIGN-SYSTEM-PHASE1-CANVAS-DEDUP.md)。<br>仍未处理：<br>• `canvas.css` 剩余 23 组：合并要越过同优先级的规则，需要先证明选择器不会命中同一元素，或在 `!important` 清理后一并处理<br>• `.canvas-project-title`、`.canvas-local-tag`、`.media-history-controls` 未被任何组件使用，可以在失效代码清理中整条删除<br>• 其他文件的 10 个重复选择器<br>• `!important` 数量未变 | [级联审计](CASCADE-AUDIT.md) | 1–2 |
| D8 | 级联顺序依赖懒加载顺序。**阶段 1 已处理可证明安全的部分**：设计 Token 位于 `@layer tokens`；React Flow 基础样式只加载一次，位于 `@layer vendor`，不再由画布懒加载块在主题之后重复插入。见 [层记录](../../release/DESIGN-SYSTEM-PHASE1-CSS-LAYERS.md)。<br>仍未处理：<br>• 应用样式（基础、主题、共享状态、组件）都未分层，因为 21 个文件共有 211 处 `!important`，分层会反转它们的优先级<br>• 组件块插在主题之后，主题仍靠特异性和 `!important` 覆盖它们<br>• `video.css` 等文件被多个块导入，插入时机取决于先打开的界面 | [级联审计](CASCADE-AUDIT.md) | 2（先清理 `!important`） |
| D9 | 19 套按钮类名；~~至少 5 套菜单实现~~；同一个素材面板里有 3 种标签页样式。**阶段 1 已统一菜单与弹层的视觉**：右键菜单、画布「更多」、项目卡片菜单、工具栏主体 / 画框菜单、项目菜单、节点搜索、选择框和参数弹层都使用同一组 Token，见 [菜单与弹层记录](../../release/DESIGN-SYSTEM-PHASE1-MENU-POPOVER.md)。<br>仍未处理：<br>• 右键菜单禁用文字 `#747882`、快捷键文字 `#9297a2` 是冷灰，保留原值<br>• 侧栏账户弹层 `.rail-user-popover`（需要已绑定账户才能渲染）<br>• 参考图预览、视频历史、候选对比、主体素材选择器这几个弹层<br>• 按钮：共用 `Button` / `ButtonLink` / `IconButton` 已建立，**只有项目首页完成替换**，见 [首页按钮记录](../../release/DESIGN-SYSTEM-PHASE1-HOME-BUTTONS.md)。其余页面仍是旧类名；共用的 `Modal` 关闭按钮和 `Confirm` 操作（`ui.tsx`）被所有页面使用，尚未替换；旧 `.button.ghost`、`.icon-button` 仍是冷灰<br>• 对话框表面：`.modal-footer` 描边 `#32363e`、`.confirm-copy` 文字 `#c2c7cf` 是冷灰<br>• 标签页 | 组件盘点 | 1 |
| D10 | ~~遗留的网站模板交互：`.btn` 悬停上浮、`.card` 上浮、项目封面 `.m-zoom` 放大、焦点环动画~~。**阶段 1 已处理**：删除悬停上浮、卡片上浮与阴影、封面放大、焦点环动画；保留按压、颜色过渡、链接下划线、封面裁切。见 [动效与面板记录](../../release/DESIGN-SYSTEM-PHASE1-MOTION-PANELS.md) | `motion/motion.css` | 已完成 |
| D11 | ~~侧面板写了过渡动画，但开关依靠 `display:none`，动画从未生效~~。**阶段 1 已处理**：开关约 0.2 秒淡入 / 淡出；关闭中不可点、不可聚焦；减少动态效果时即时完成 | `canvas.css` 中的 `.canvas-library` / `.canvas-inspector` | 已完成 |
| D12 | 口型同步、资产详情使用浏览器原生的 `select`、`audio`、`video` 控件，浅灰色的音频条与深色界面冲突 | 口型同步、资产详情截图 | 1 |
| D13 | 多个样式文件整份写在一行 | [级联审计](CASCADE-AUDIT.md) | 1（随迁移逐个展开） |
| D14 | 不同页面的页头和网格不一致：工作流页没有面包屑，内容起点与其他页面不同，并带有宣传性质的横幅 | 工作流页截图 | 1 |

## 交互与结构问题（不属于样式治理，需另行规划）

这些问题在视觉基线中已确认，但涉及交互逻辑或挂载方式，不在 Design System 阶段处理：

- 选中素材会自动弹出创作面板，与两侧浮动面板叠加后，内容区被大量遮挡，而且会挡住对节点和缩放按钮的点击。
- 新建节点总是出现在同一个位置，互相重叠。
- 完整工作区（剧本、剪辑、成片、口型、分享）放在弹窗中，按 `Esc` 会直接关闭整个工作区；时间线没有键盘快捷键。
- 画布缩到全局视图时，节点文字实际只有 4.4–8.5px；需要按缩放级别调整显示内容。
- 媒体节点尺寸固定为 264×214，与素材画幅无关，造成黑边。
- 图像生成失败时不显示原因；任务列表把同一条错误重复显示两遍，内容还有误导。
- 安装向导默认勾选全部 174 GB 模型；「准备就绪」页面点完成会返回 409。
