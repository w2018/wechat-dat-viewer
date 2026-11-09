<div align="center">

<h1>微信 4.x 图片 / 视频查看器</h1>

<p>本地查看、导出、清理微信电脑版缓存的聊天图片与视频。零第三方依赖，默认只读。</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/dependencies-none-green" alt="Dependencies">
  <img src="https://img.shields.io/badge/mode-local_only-lightgrey" alt="Mode">
</p>

</div>

---

## 风险与合规提醒

**⚠️ 此操作非常危险，可能导致不可逆的数据丢失！** 删除功能会把媒体文件移入系统回收站，微信聊天里对应的图片 / 视频会失效；涉及工作资料、证据保全或单位设备时，请先导出备份并确认没有留存义务。

### 法律风险

- **适用范围**：仅限在**本人所有或已获授权的设备**上管理**本人账号**的本地缓存。不得用于访问他人设备、账号或数据。
- **隐私与个人信息**：解密出的图片、视频可能包含他人肖像、聊天内容、证件、住址、工作资料。未经授权查看、导出、复制或传播，可能触及《民法典》隐私权与肖像权、《个人信息保护法》《数据安全法》《网络安全法》乃至《刑法》相关规定。
- **著作权**：群聊图片 / 视频多属他人作品，导出后仅供个人留存，不得公开传播、二次发布或商用。
- **留存义务**：工作群与业务往来资料可能受单位制度、审计或诉讼证据保全要求约束，删除前务必确认合规。
- **技术边界**：本工具不破解账号口令、不绕开微信服务端鉴权、不访问微信服务器，仅读取本机已缓存文件；不得用于规避技术保护措施或侵犯他人权益。
- **免责**：工具按「现状」提供，不对数据丢失、隐私泄露或任何法律后果负责。使用即表示你已确认有权处理这些数据，并自行承担全部合规责任。

---

## Features

- **双分区**：图片分区按会话 + 月份解密看图；视频分区按月份播放明文 MP4（支持拖动）。
- **自动发现数据目录**：读注册表记录的路径、常见位置与各盘根目录找到微信 4.x 数据目录，结果保存到 `wechat_data_root.dat`。
- **重新扫描**：顶部按钮强制重扫全部会话的大小、文件数与日期；首次加载与重新扫描都显示进度条、耗时和完成状态（后台线程，不阻塞界面）。
- **勾选统计**：实时显示已选数量与总大小，按整组文件（高清图 / 缩略图 / 封面）累加。
- **悬浮信息**：路径、日期时间、大小（自动 KB / MB / GB）、像素尺寸、时长、硬链接标记。
- **批量导出**：打包 ZIP 到 `exports/`，绝不写回微信目录。
- **批量删除**：默认关闭，需显式开启；两步确认后分批移入系统回收站。
- **降级提示**：整组都解不出或视频无法播放时才显示简洁占位图，不出现破图；`wxgf` 高清原图缺 ffmpeg 时悬浮信息标注「原图需 ffmpeg」，缩略图照常显示。
- **零依赖 / 本地**：纯 Python AES，服务只绑定 `127.0.0.1`，看图与播放走内存响应。

## Requirements

- Windows + Python 3.10+（仅标准库）
- 微信电脑版 4.x 的本地数据目录：启动时自动扫描；也可用 `--data-root` 或环境变量 `WECHAT_DATA_ROOT` 指定
- 扫描结果保存在当前文件夹的 `wechat_data_root.dat`，下次直接复用；该文件已被 `.gitignore` 排除
- 可选：**完整版** ffmpeg（需含 HEVC demuxer 与 MJPEG encoder），用于解码 `wxgf` 高清原图；放到 PATH 或用 `--ffmpeg` / `WECHAT_FFMPEG` 指定。未配置时按「高清图 → 主图 → 缩略图」回退，明文 JPEG 缩略图仍可正常显示。工具不会自动扫描 ffmpeg 安装位置

## Quick Start

```bash
# 1) 自检（自动扫描微信数据目录，结果写入 wechat_data_root.dat）
python wechat_dat_viewer.py probe

# 2) 启动（默认端口 56789）
python wechat_dat_viewer.py serve --open

# 若自动扫描没找到，手动指定一次即可
python wechat_dat_viewer.py probe --data-root "D:\YourPath\xwechat_files"
# 或：set WECHAT_DATA_ROOT=D:\YourPath\xwechat_files
```

也可以双击 `start_viewer.bat`（只读）或 `start_viewer_delete.bat`（启用删除）。启动后访问 `http://127.0.0.1:56789`。

命令行导出（不启动网页）：

```bash
python wechat_dat_viewer.py export \
  --session <32位会话哈希> --month 2026-09 \
  --out "./exports/images" --limit 50
```

常用参数：`--data-root`、`--account`、`--sessions-csv`、`--ffmpeg`、`--port`、`--allow-delete`、`--open`。

## 使用说明

| | 图片分区 | 视频分区 |
| --- | --- | --- |
| 数据 | `msg/attach/<会话>/<年月>/Img/*.dat`（加密） | `msg/video/<年月>/*.mp4`（明文） |
| 组织 | 会话 + 月份 | **仅按月份**，路径不含会话信息，无法按群归属 |
| 查看 | 灯箱看原图，优先 `_h.dat` 高清 | 灯箱播放，HTTP 206 Range |
| 卡片 | 文件名前缀 + 大小 | 同左 |

会话下拉框按最近活动日期倒序，选项按「起始 → 结束」显示起止年月日、占用大小（自动换算 KB / MB / GB）与文件数。**占用与文件数在 CSV 缺失时自动实时扫描文件系统**（只读遍历，结果缓存在内存、不落盘，298 个会话约 1 秒）；也可用 `--sessions-csv` 提供预生成清单（列名 `session_hash,logical_size_MB,file_count`）。清单文件含真实会话哈希，已由 `.gitignore` 排除，不要提交。

删除链路：`preview` 生成完整文件清单 + 一次性令牌 → 前端手工输入 `MOVE_TO_RECYCLE_BIN` → `commit` 校验令牌与确认词 → 每批 ≤10 个经 `SHFileOperationW + FOF_ALLOWUNDO` 移入回收站，逐批验证、失败即停，并写 `delete_log.jsonl`。数据库与配置文件一律拒绝操作。硬链接文件删除后不一定立刻释放空间，需清空回收站才真正腾出磁盘。

## 技术实现

- 图片 `.dat` 为微信 4.0 的 V2 格式：15B 头 `07 08 56 32 08 07` + AES-128-ECB 段（PKCS#7）+ 单字节 XOR 尾段。密钥可纯离线推导：AES key = `MD5(UIN + wxid)[:16]`，XOR key = `UIN & 0xFF`，UIN 取自 `%APPDATA%\Tencent\xwechat\net\kvcomm\key_<uin>_*.statistic` 文件名。实现为纯 Python，已与 OpenSSL 交叉验证。
- 部分图片是微信自研 `wxgf`（内部 Annex-B HEVC），完整版 ffmpeg 可从 VPS 起始码 `00 00 00 01 40 01` 截取 HEVC 流并在内存中转成 JPEG；缺 ffmpeg 时自动回退到组内可解出的 JPEG（高清图或缩略图），悬浮信息标注「原图需 ffmpeg」。
- 视频为明文 MP4；分辨率与时长由 MP4 容器头（`mvhd` / `stsd`）解析，无需 ffprobe。
- 视频按月份全局存放，**无法按群管理**；按群清理请用微信自带的「设置 → 存储空间管理 → 聊天数据管理」。

## 目录结构

```
wechat-dat-viewer/
├── wechat_dat_viewer.py        # 主程序：probe / serve / export + 网页界面
├── wechat_dat_core.py          # AES、V2 解析、密钥发现、MP4 头、回收站
├── start_viewer.bat            # 只读启动
├── start_viewer_delete.bat     # 带删除启动
├── .gitignore
├── LICENSE
└── README.md
```

`exports/`、`delete_log.jsonl` 与 `wechat_data_root.dat` 在运行时生成，均已被 `.gitignore` 排除。

## 更新日志

### v0.2.0

- 会话占用与文件数不再依赖外部 CSV：缺失时实时扫描文件系统，结果缓存在内存
- 新增「重新扫描」按钮与进度条、耗时、完成状态；首次加载也走同一后台扫描流程
- 下拉框日期改为「起始 → 结束」，大小自动换算 KB / MB / GB
- 修正 `wxgf` 误判：缩略图与大图按「高清 → 主图 → 缩略图」回退正常显示，悬浮信息标注「原图需 ffmpeg」
- README 顶部区域居中，徽标改回可正确渲染的路径形式

### v0.1.0

- 初始发布：双分区看图 / 播放、勾选统计、悬浮信息、批量导出、两步确认删除（系统回收站）、自动发现数据目录、MIT 许可证

## FAQ

- **悬浮信息显示「原图需 ffmpeg」**：缩略图和大图仍可看（回退到明文 JPEG），只是 `wxgf` 高清原图解码不了；安装完整版 ffmpeg 后用 `--ffmpeg` 或 `WECHAT_FFMPEG` 指定即可。
- **视频出现「不支持播放，需要解码器」**：浏览器无法解码该编码，可用系统播放器打开导出的 MP4。
- **提示「未找到微信 4.x 数据目录」**：确认微信 PC 版登录过并生成了 `xwechat_files`；用 `--data-root` 指定一次，或设置 `WECHAT_DATA_ROOT`。
- **换了数据目录 / 迁移了微信文件**：删掉当前文件夹的 `wechat_data_root.dat` 再启动，或用 `--data-root` 覆盖并重写配置。
- **Python 启动报 `SRE module mismatch`**：`PYTHONHOME` 指向了损坏的解释器，先清空该环境变量；启动器已处理。
- **图片打不开**：先跑 `probe` 检查密钥；`wxgf` 高清原图需完整版 ffmpeg，缩略图通常仍可显示。
- **删了空间没变**：硬链接仍被别处引用，或文件还在回收站占空间。
- **找不到占用最大的群**：下拉框按最近活动日期倒序，可按选项里自动换算的大小数值识别；也可提供按大小排序的 `--sessions-csv`。

## 只读承诺

除显式开启的「删除勾选」外，工具对微信目录一律只读（`open(..., 'rb')`），不写入、不移动、不重命名、不删除；导出与日志均落在工具目录。不打开消息数据库，不解析聊天文本。

## License

MIT © 2026 w2018. See [LICENSE](LICENSE).
