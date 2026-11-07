# SeptnetScore · 七天学堂查分与年级排名分析工具

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Web%20%7C%20Android-green.svg)]()
[![API Version](https://img.shields.io/badge/Septnet%20API-v4.6.4-orange.svg)]()

> 基于七天学堂 (`cc.septnet.student` v4.6.4) 原生网络层协议与加解密体系逆向分析构建的开源查分与排名分析工具。
> 提供 **本地 Web 看板** 与 **独立 Android APK** 两种运行形态，无需充值会员即可自动解锁查看年级真实排名与百分位。

---

## ✨ 核心特性

- 🔓 **免 VIP 解锁全科年级真实排名**
  官方对于普通非 VIP 账号隐藏年级名次（VIP-only 接口返回 405，界面显示 `处于年级***`）。本项目通过底层 `Question/Subjects` 返回的全校考生总数（`studentCount`）与百分位（`sortDesc`）精确反推总分及各单科在年级中的真实排位（例如：年级第 578 / 1489 名）。
- 📊 **高考赋分与卷面原始分双模对照**
  针对新高考选考科目（政治、历史、地理、物理、化学、生物等），同时展示高考赋分转换后成绩与卷面原始分。
- 🎯 **AI 学情诊断与整体表现评价**
  自动抓取官方微服务生成的智能学情诊断总结（学科优势、相对薄弱点及整体定位）。
- 📝 **单科小题全校选项作答分布**
  支持查看单科各小题的全校考生作答选项占比分布（A/B/C/D 各项百分比）与全校正确率。
- 📱 **双端开源支持**
  - **PC / Web 看板**：基于 Python 原生网络层与自适应 CSS 深色主题仪表盘。
  - **Android 手机客户端**：Kotlin 原生封装微服务加解密体系，手机安装后完全脱离电脑独立运行。
- 🔒 **本地凭据持久化与隐私安全**
  会话信息保存在本地 `session.json`（或 Android `SharedPreferences`），绝不上报任何第三方服务器。

---

## 🏗️ 协议与底层逆向机制

1. **微服务集群**
   - 账号登录与用户信息微服务：`https://szone-my.7net.cc/`
   - 考试与学科成绩微服务：`https://szone-score.7net.cc/`

2. **原生加解密流程（LocalAesCryptoUtil / septnetlive）**
   - **客户端密钥生成**：每次会话随机生成 32 字节 AES-256 密钥。
   - **RSA 密钥加密**：使用官方内置 1024-bit RSA 公钥加密 AES 密钥，生成 `bk` 请求头。
   - **密钥协商**：向 `POST https://szone-my.7net.cc/user` 登记 `bk`。
   - **报文加密**：请求参数以 `;` 拼接后经 `AES-256-GCM` 加密，生成 12 字节随机 IV（`bn`）与密文+Tag（`bp`）。注意请求头名称 `bk`、`bn`、`bp` 服务端大小写敏感，必须全小写发送。
   - **响应解密**：
     - 动态业务报文通过协商的 `raw_aes_key` 与返回的 `bn` IV 进行 `AES-256-GCM` 解密。
     - 考试列表等静态报文采用固化 AES-256-ECB 密钥（`c0f1a30cba2147949ee71cf71cba3c20`）解密。

3. **排名计算公式**
   $$\text{年级排名} = \mathrm{round}\left(\frac{\text{studentCount} \times \text{percentile}}{100}\right)$$

---

## 🚀 快速开始

### 方式一：运行本地 Web 看板 (Python)

#### 1. 环境准备
需要 Python 3.8 或更高版本，依赖 `pycryptodome`：
```bash
pip install pycryptodome
```

#### 2. 启动服务
```bash
# 启动本地服务（默认端口 8765）
python app.py 8765

# 或在 Windows 上直接双击运行：
start_app.bat
```

#### 3. 访问看板
在浏览器中打开：
```
http://127.0.0.1:8765
```
输入七天学堂手机号与密码即可登录查分。

---

### 方式二：编译与安装 Android APK

工程位于 `septnet_app/` 目录：

#### 1. 编译 APK
```bash
cd septnet_app
./gradlew assembleDebug
```
编译产物位于 `app/build/outputs/apk/debug/app-debug.apk`。

#### 2. 安装至手机
通过 USB 数据线、微信传输助手或 QQ 发送至 Android 手机点击安装即可。

---

## 📂 项目结构

```
score_app/
├── api_client.py           # 核心 API 客户端（包含原生加解密、协议报文与折算算法）
├── app.py                  # 本地 HTTP 服务端与 API 代理路由
├── index.html              # 现代化深色响应式查分与排名看板前端
├── session.example.json    # 会话配置模板
├── start_app.bat           # Windows 一键启动脚本
├── README.md               # 项目技术文档
└── LICENSE                 # 开源许可协议 (MIT)
```

---

## ⚖️ 免责声明 (Disclaimer)

1. 本项目仅供网络安全、逆向工程与前后端通信协议的技术研究与个人学习使用。
2. 严禁将本项目及其衍生代码用于任何商业用途、非法盈利或侵犯他人合法权益的场景。
3. 查分凭据均在本地客户端与官方官方服务器之间直接通信，请妥善保管个人账号密码。

---

## 📄 License

本项目采用 [MIT License](LICENSE) 开源许可证。
