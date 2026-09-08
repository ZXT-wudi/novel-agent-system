# 知识图谱可视化升级（世界图谱 + 关系网络）Spec

## Why
当前知识图谱的两个视图过于朴素：「关系网络」是纯色几何节点 + 直线连线，章节节点混入导致图面拥挤，已有角色立绘未接入；「世界观地图」只是圆环布局的圆点 + 随机虚线，谈不上"地图"。用户希望展示更形象生动，并允许调用图像模型生成插画。

## What Changes
- **关系网络升级**：角色节点接入已生成立绘作圆形头像（无立绘回退首字圆）；关系连线改为曲线 + 方向箭头 + 按类型着色；图例支持按关系类型筛选；章节节点默认隐藏、可开关；节点详情面板展示立绘。
- **世界观地图升级**：新增「插画模式」——AI 生成小说级世界地图插画（1 张/小说，入库缓存、按需生成），SVG 交互热区叠加其上；保留升级版「示意模式」（有机大陆形状、分类配色、按共享角色画真实连线），两模式可切换。
- **区域插画**：区域详情面板加「生成区域插画」按钮，按需生成、入库缓存。
- **图像模型可配置**：模型名抽到环境变量 `IMAGE_MODEL`，默认 `Tongyi-MAI/Z-Image-Turbo`。
- **BREAKING**：无（全部为增量修改，图谱 GET 接口响应只增字段不删字段）。

## Impact
- Affected specs: 无既有 spec 直接受影响（此前 `redesign-editorial-ui-and-polish-agent` 涉及的抽取/保存链路不动）。
- Affected code:
  - `app/llm/siliconflow.py`（generate_image 模型名读环境变量）
  - `app/models/novel_image.py`（新增）、`app/models/__init__.py`（注册）
  - `app/services/image_service.py`（世界地图/区域插画生成与缓存）
  - `app/services/knowledge_extractor.py`（build_graph_data 附带 images / character_images）
  - `app/api/knowledge.py`（新增 world-image / region-image 端点）
  - `static/js/knowledge-graph.js`（两个视图重做渲染）
  - `static/css/style.css`（新样式）、`static/index.html`（JS 版本号递增）

## ADDED Requirements

### Requirement: 图像模型可配置
系统 SHALL 从环境变量 `IMAGE_MODEL` 读取图像模型名，未配置时默认 `Tongyi-MAI/Z-Image-Turbo`。

#### Scenario: 未配置环境变量
- **WHEN** 环境变量 `IMAGE_MODEL` 不存在
- **THEN** `generate_image` 使用 `Tongyi-MAI/Z-Image-Turbo`，行为与现状一致

#### Scenario: 配置了环境变量
- **WHEN** `IMAGE_MODEL=某模型名`
- **THEN** 图像生成请求的 `model` 字段使用该值

### Requirement: 小说级世界地图插画
系统 SHALL 提供 POST `/{novel_id}/knowledge/world-image` 端点：依据小说标题、题材、世界设定（地点/势力等 world 元素）构造提示词，调用图像模型生成横版（1344x768）艺术风世界地图插画，下载落盘到 `static/novel_images/` 并以 `(novel_id, image_type="world_map", image_key="")` 唯一键缓存到 `novel_images` 表；已存在缓存时直接返回，`force=true` 时重新生成并覆盖。

#### Scenario: 首次生成
- **WHEN** 用户点击「生成世界地图插画」且无缓存
- **THEN** 返回 `{"image_url": "/static/novel_images/..."}`，再次请求命中缓存

#### Scenario: 强制重新生成
- **WHEN** 请求携带 `force=true`
- **THEN** 重新生成并更新表记录与文件，返回新 URL

### Requirement: 区域插画按需生成
系统 SHALL 提供 POST `/{novel_id}/knowledge/region-image` 端点：入参 `{region_name, description?, force?}`，以区域名 + 描述 + 关联角色 + 小说题材构造提示词，生成 1024x1024 插画，以 `(novel_id, image_type="region", image_key=区域名)` 缓存，语义同上。

### Requirement: 图谱数据附带图像信息
GET `/{novel_id}/knowledge/graph` 响应 SHALL 新增：
- `images: {world_map: url|null, regions: {区域名: url}}`（来自 novel_images 表）
- `character_images: {角色名: url}`（来自 character_images 表，取该角色最新一条，作为关系网络头像来源）

已有字段（nodes/links/regions/stages/novel_title）保持不变。

### Requirement: 关系网络形象化渲染
前端关系网络视图 SHALL：
- 角色节点优先用 `character_images` 立绘渲染圆形头像（SVG clipPath 裁剪），无立绘回退现有首字圆样式；
- 角色-角色关系连线渲染为带方向箭头的曲线，按关系类型着色，悬停高亮保留；
- 图例每一项可点击开关对应关系类型的连线显隐；
- 章节节点默认隐藏（连带其 appears_in 连线），提供开关按钮显示；隐藏章节后无任何可见连线的孤立节点不渲染。

#### Scenario: 已有立绘的角色
- **WHEN** 渲染关系网络且 `character_images` 含该角色
- **THEN** 节点显示圆形头像图片，而非纯色首字圆

#### Scenario: 关系类型筛选
- **WHEN** 用户点击图例中某关系类型使其熄灭
- **THEN** 该类型连线即时隐藏，再次点击恢复

### Requirement: 世界地图双模式展示
前端世界观地图视图 SHALL：
- 提供「插画模式 / 示意模式」切换（会话内记忆，有插画时默认插画模式，否则默认示意模式）；
- 插画模式：地图插画作背景，区域以透明热区圆点叠加其上（悬停描边、点击进详情）；无插画时显示生成引导卡片（含 loading / 失败重试态）；
- 示意模式：区域渲染为有机大陆形状（不规则弧形闭合路径），按分类配色并带分类角标，区域间按「共享出场角色」绘制真实连线（取代现有随机连线）。

#### Scenario: 无插画时进入地图视图
- **WHEN** 该小说尚未生成世界地图插画
- **THEN** 默认示意模式可用，插画模式位置显示「生成世界地图插画」引导按钮

#### Scenario: 生成完成后
- **WHEN** 世界地图插画生成成功
- **THEN** 自动切换到插画模式展示背景 + 热区

### Requirement: 区域详情插画区
区域详情面板 SHALL 新增插画区块：有缓存插画则展示；无则提供「生成区域插画」按钮（loading / 失败提示），成功后原位展示。

## MODIFIED Requirements
（无——本 spec 只新增能力，不修改既有需求的语义。）

## REMOVED Requirements
（无。）
