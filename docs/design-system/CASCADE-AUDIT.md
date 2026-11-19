# 级联结构审计

本页记录前端样式的加载顺序、覆盖机制和统计数字，修改样式前请先阅读。统计时间为 2026-11-19，对应设计系统阶段 0 完成后的分支状态；数字会随后续治理变化，更新时请注明日期。规则见 [Design System](README.md)。

## 加载顺序

```text
main.tsx
  1. design/tokens.css        只有自定义属性，位置不影响级联
  2. Root.tsx → setup/setup.css
  3. styles.css               全局基础样式与历史别名（含 @xyflow/react 样式）
  4. studio-theme.css         html[data-theme="studio"] 覆盖层
  5. management.css           设置 / 管理页覆盖层
  6. motion/motion.css        遗留交互层（阶段 0 后只剩仍生效的规则）
App 及各工作区按需懒加载，组件 CSS 在对应 chunk 加载时插入：
  Canvas → canvas.css、review-experience.css
  GenerationComposer → generation.css、studio-composer.css
  VideoComposer / VideoViewer / CanvasVideoPlayer / AudioComposer / VideoEnhanceComposer → video.css
  ……（共 40 个组件级样式文件）
```

**关键事实：组件样式的级联顺序取决于运行时加载顺序。** 同一个文件（例如 `video.css`）被 5 个组件导入，先打开哪个工作区，决定了它插入页面的位置。全局主题文件最先加载，为了覆盖之后加载的组件样式，只能依靠更高的特异性或 `!important`。这是覆盖不断升级的根本原因。

## 四种覆盖机制

1. **主题前缀提高特异性。** `studio-theme.css` 用 `html[data-theme="studio"]` 加 `:is(...)` 压过组件规则，`management.css` 同理。
2. **`!important`。** 全部 206 处，`canvas.css` 占 107 处。
3. **同一文件的后置覆盖块。** `canvas.css` 后半部分重复定义了前面的组件（工具栏、节点、顶栏等），并大量配合 `!important`。共有 31 个选择器在顶层被完整定义了两到三次。
4. **数值别名并行。** `--canvas-*`、`--admin-*`、`--setup-*` 和根变量重复写着同样的颜色。阶段 0 已把它们统一指向 Token。

## 统计（阶段 0 完成后）

| 文件 | 行数 | `!important` | 十六进制字面量 | `var()` | 重复顶层选择器 |
| --- | ---: | ---: | ---: | ---: | ---: |
| canvas.css | 1983 | 107 | 210 | 83 | 31 |
| setup/setup.css | 1628 | 18 | 95 | 66 | 0 |
| canvas-project-menu.css | 56 | 14 | 6 | 45 | 0 |
| timeline.css | 18 | 12 | 45 | 40 | 1 |
| studio-theme.css | 61 | 9 | 9 | 96 | 0 |
| comfy.css | 716 | 6 | 97 | 13 | 0 |
| video.css | 424 | 5 | 136 | 43 | 5 |
| styles.css | 1736 | 3 | 101 | 136 | 0 |
| 全部 41 个文件 | — | 206 | 1542 | 978 | 41 |

颜色字面量按色系分类：中性灰 543；旧冷蓝灰 374；旧绿色 203；黑白透明叠加 112；琥珀 92；玫瑰强调 58；暖墨 42。旧色系集中在 `canvas.css`（绿 52 / 冷蓝 45）、`comfy.css`（绿 60）、`subjects.css`（冷蓝 53）、`styles.css`、`generation.css`、`workflows.css`。

另有若干文件整份写在一行里（`canvas-runs.css`、`speech.css`、`lipsync.css`，以及 `timeline.css`、`video.css` 的大部分），难以审阅和比较差异。

## 阶段 0 已移除的失效代码

- `motion/motion.js`：它挂载的元素（`.nav`、带 `role=tablist` 的 `.tabs`、`[data-m-count]`、`[data-m-loop]`、`.m-switch`）在应用中都不存在。
- `motion.css` 中所有选择器都匹配不到元素的规则：导航菜单、标签指示条、箭头、胶囊、`.link`、`.field`、开关、复选框、数字滚动、循环动画。仍生效的规则原样保留。
- `index.html` 上只被失效规则读取的模板属性：`data-type`、`data-radius`、`data-buttons`、`data-motion`，以及两个 meta 标签。
- `.canvas-zoom-controls` 被完全覆盖的前置定义、按钮规则、悬停规则，以及一条失效的媒体查询声明。

判断失效的标准：规则的每个选择器在 TSX 中都找不到对应的类名，包括模板字符串和条件拼接出的类名，并且有渲染指纹佐证。选择器列表只要有一个参数仍生效，整条规则保留，不删减其中的参数，因为 `:is()` 的特异性取各参数中的最大值，删减会改变覆盖结果。

## 关于 `@layer`

把全局样式放进 `@layer` 可以让级联顺序不再依赖加载顺序，但未分层的规则总是优先于分层规则，引入后会整体改变现有的覆盖结果。它适合在 `!important` 和重复定义清理之后作为单独阶段实施，阶段 0 不做。
