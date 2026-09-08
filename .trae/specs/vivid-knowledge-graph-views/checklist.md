# Checklist

- [x] `generate_image` 模型名读取 `IMAGE_MODEL` 环境变量，未配置时默认 `Tongyi-MAI/Z-Image-Turbo`
- [x] `novel_images` 表模型已创建并注册，启动 `create_all` 自动建表，唯一约束 `(novel_id, image_type, image_key)` 生效
- [x] `generate_and_save_world_map`：首次生成落盘 + 入库；重复调用命中缓存；`force=true` 覆盖更新
- [x] `generate_and_save_region_image`：按区域名缓存与覆盖，提示词含区域描述/关联角色/题材
- [x] `GET /{novel_id}/knowledge/graph` 响应新增 `images` 与 `character_images` 字段，旧字段不变
- [x] POST world-image / region-image 端点可用，缺 region_name 返回 422，失败返回中文错误
- [x] 关系网络：有立绘的角色节点渲染圆形头像，无立绘回退首字圆
- [x] 关系网络：relation 连线为曲线 + 箭头 + 按类型着色，悬停高亮不回归
- [x] 关系网络：图例点击可开关关系类型显隐
- [x] 关系网络：章节节点默认隐藏、可开关，隐藏后无孤立节点残留
- [x] 关系网络：角色详情面板展示立绘（如有）
- [x] 世界地图：插画/示意模式切换可用，默认规则正确（有插画默认插画模式）
- [x] 世界地图：无插画时显示生成引导卡，含 loading 与失败重试；生成成功自动切入插画模式
- [x] 世界地图：示意模式为有机大陆形状 + 分类配色/角标，区域连线为共享角色真实连线（非随机）
- [x] 区域详情：插画区块按需生成并缓存展示
- [x] `py_compile` 全部改动 py 文件通过
- [x] `node --check` knowledge-graph.js 通过
- [x] index.html 中 knowledge-graph.js 版本号已递增
