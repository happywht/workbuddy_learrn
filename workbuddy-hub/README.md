# WorkBuddy 共学入口

这是一个通用的多页面 WorkBuddy 学习与共享站点。它不再把所有岗位的案例堆在一个长页面里，而是把公共认知与业务方向分开维护。

## 页面结构

- `index.html`：公共入口，只负责方向选择和公共课程入口。
- `paths/onboarding.html`：第一次接触，包含安装、工作空间、首次任务和飞书连接。
- `paths/project.html`：项目与设计，仅包含项目周报风险归拢。
- `paths/management.html`：经营与管理，仅包含合同回款预警和人员工作量验证。
- `paths/briefing.html`：综合与汇报，仅包含周报转结论型 PPT。
- `resources/ai-evolution.html`：9 页 AI 产品演进阅读器。
- `resources/bluebook-course.html`：WorkBuddy 蓝皮书第 1-3 章连续视频课程。
- `resources/advanced-automation.html`：15 页 WorkBuddy 高阶自动化实战阅读器。
- `agent-skill/SKILL.md`：供 WorkBuddy Agent 读取的案例或 Skill 发布指导。

方向页之间不互相链接，只能返回公共入口或进入公共课程。该设计实现内容呈现隔离；如需按用户或部门做严格访问控制，部署时仍需增加服务端身份认证和授权。

## 本地浏览

在项目根目录运行：

```powershell
python workbuddy-hub/serve.py --port 4173
```

然后访问 `http://127.0.0.1:4173/workbuddy-hub/`。

这个本地服务器支持 MP4 分段读取，视频章节定位可以正常工作；通过 HTTP 打开也能确保下载文件和浏览器剪贴板能力工作稳定。
