# Android 原生运行时第三方许可与署名

核验日期：2026-10-09。

本清单对应 `app/build/reports/native/runtime-inventory.json` 中实际解析的
`debugRuntimeClasspath` **13 个 Maven 坐标**，不是 Gradle 缓存中所有包的清单。
这是解析后的组件范围，不表示每个组件的全部文件都转成 DEX；本清单保守保留其授权。
JDK、Gradle、AGP、Android SDK、测试工具及 Kotlin 编译器不因此成为 APK 运行时组件。
Android System WebView 由设备提供；本 APK 没有携带整个 Chromium 浏览器。
未使用 Capacitor 或 Cordova。

每个坐标已核对固定版本 POM、官方源码 JAR 的版权头及可用许可文件。
POM 中 13 项均声明 Apache-2.0，但源码进一步包含 Chromium BSD 条款及 Kotlin
数学实现的 Boost-1.0；这两项不能被 POM 的主许可标签替代。
本项目未直接修改以下第三方源码；打包、DEX 转换与资源合并不改变其授权。

## 完整许可文本的携带方式

- **Apache-2.0**：完整文本为仓库根目录 [`LICENSE`](../LICENSE)，构建时须原样
  携带为 APK 的 `assets/public/notices/LICENSE.txt`。以下 Apache 组件共用这一份完整
  授权文本，不仅携带网页链接。上游文本：[Apache 官方许可证](https://www.apache.org/licenses/LICENSE-2.0.txt)。
- **BSD-3-Clause（Chromium）**：本文件末尾完整保留条款和对应署名。
- **Boost-1.0**：本文件末尾完整保留条款和对应署名。
- **MIT（前端）**：React 19.2.8、React DOM 19.2.8 与 scheduler 的完整许可和版本由
  固定依赖构建生成 `mobile/dist/THIRD_PARTY_LICENSES.txt`，应另行携带为
  `assets/public/notices/THIRD_PARTY_LICENSES.txt`。其内容不计入下面 13 个原生坐标。
- **本署名文件**：须以内容完全相同的
  `assets/public/notices/THIRD_PARTY_ANDROID_NOTICES.txt` 携带，并在内部 APK 验证中检查。
  使用 `.txt` 与原生本地资源白名单一致；仓库源码仍保留此 Markdown 文件。

仅拥有本 Markdown 或公开 URL，而缺少上述完整 Apache/MIT 文件，不构成完整打包验收。

## 13 个原生运行时组件

### 1. androidx.annotation:annotation-experimental:1.4.1

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/annotation/annotation-experimental/1.4.1/annotation-experimental-1.4.1.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/annotation/annotation-experimental/1.4.1/annotation-experimental-1.4.1-sources.jar)
- POM SHA256：`fe57b228417f4d7c677903dc61fb4a7cf993d603499de26d8d8113e477cc4f1b`
- 源码 JAR SHA256：`783a221a7c1093ff8932053998a69a24489f7930806a32b55366108146d29c1d`
- 已核对源码版权头：2019、2020；完整保留见下方 AndroidX 署名段。

### 2. androidx.annotation:annotation-jvm:1.8.1

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/annotation/annotation-jvm/1.8.1/annotation-jvm-1.8.1.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/annotation/annotation-jvm/1.8.1/annotation-jvm-1.8.1-sources.jar)
- POM SHA256：`d49203733aa6fae046c3a3de4e796eed347595755486a64273989844759750b4`
- 源码 JAR SHA256：`5add69d7bb907ade52823bf4b15730a1a32cfce6657bfbe7eb865b00107a6369`
- 已核对源码版权头：2013–2024；完整保留见下方 AndroidX 署名段。

### 3. androidx.arch.core:core-common:2.0.0

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/arch/core/core-common/2.0.0/core-common-2.0.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/arch/core/core-common/2.0.0/core-common-2.0.0-sources.jar)
- POM SHA256：`4b6f1d459ddd146b4e85ed6d46e86eb8c2639c5de47904e6db4d698721334220`
- 源码 JAR SHA256：`0321dc07683a12b333040592c90fa023aca04d0df42af740798c0f745c788c73`
- 源码版权头：`Copyright 2018 The Android Open Source Project`。

### 4. androidx.collection:collection:1.0.0

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/collection/collection/1.0.0/collection-1.0.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/collection/collection/1.0.0/collection-1.0.0-sources.jar)
- POM SHA256：`a7913a5275ad68e555d2612ebe8c14c367b153e14ca48a1872a64899020e54ef`
- 源码 JAR SHA256：`3dcefe7a84308582986dda5e2cf66fd3bd279f076e3a58c377e6ed66d5233b9d`
- 源码版权头：`Copyright 2018 The Android Open Source Project`。

### 5. androidx.core:core:1.1.0

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/core/core/1.1.0/core-1.1.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/core/core/1.1.0/core-1.1.0-sources.jar)
- POM SHA256：`dae46132cdcd46b798425f7cb78fd65890869b6d26101ccdcd43461a4f51754c`
- 源码 JAR SHA256：`9677b5fe2d1b444a68af62212e99075a8cc39045f1d4821b35c83d13c8aaf04e`
- 已核对源码版权头：2009、2011–2019；完整保留见下方 AndroidX 署名段。

### 6. androidx.lifecycle:lifecycle-common:2.0.0

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/lifecycle/lifecycle-common/2.0.0/lifecycle-common-2.0.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/lifecycle/lifecycle-common/2.0.0/lifecycle-common-2.0.0-sources.jar)
- POM SHA256：`04d525073469214d0c99e81aaa875dd548ba32b82945abd8326bc50229df700d`
- 源码 JAR SHA256：`8e85da54078b60444cffe7c581e1efd82942eb519db682046f26ff7d7b868065`
- 源码版权头：`Copyright (C) 2017 The Android Open Source Project`。

### 7. androidx.lifecycle:lifecycle-runtime:2.0.0

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/lifecycle/lifecycle-runtime/2.0.0/lifecycle-runtime-2.0.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/lifecycle/lifecycle-runtime/2.0.0/lifecycle-runtime-2.0.0-sources.jar)
- POM SHA256：`a92a46fa7aec8ac326a5d578734a2d5b63206976996b9e06cae171b35b0ab6de`
- 源码 JAR SHA256：`472d99cf093b3b65d24a5707138ce51b160eb81a0ed59095ca8c8e0883ab1524`
- 源码版权头：`Copyright (C) 2017 The Android Open Source Project`。

### 8. androidx.versionedparcelable:versionedparcelable:1.1.0

- 许可：Apache-2.0；作者/版权主体：The Android Open Source Project。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/versionedparcelable/versionedparcelable/1.1.0/versionedparcelable-1.1.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/versionedparcelable/versionedparcelable/1.1.0/versionedparcelable-1.1.0-sources.jar)
- POM SHA256：`c729c7be0cc06323bda829d460666e79dbd43b799a21089a44bd3b293dc253b5`
- 源码 JAR SHA256：`135016af471acf4cd9583d36ceb779710c6b46812ccaaef7c526d5d60eae6b0b`
- 源码版权头：`Copyright 2018 The Android Open Source Project`。

### 9. androidx.webkit:webkit:1.14.0

- 主许可：Apache-2.0；包含 `org/chromium/support_lib_boundary/**` 的 BSD-3-Clause
  来源代码。作者/版权主体：The Android Open Source Project、The Chromium Authors。
- [固定 POM](https://dl.google.com/dl/android/maven2/androidx/webkit/webkit/1.14.0/webkit-1.14.0.pom)
  · [官方源码 JAR](https://dl.google.com/dl/android/maven2/androidx/webkit/webkit/1.14.0/webkit-1.14.0-sources.jar)
- POM SHA256：`230b7ba1631c5f6baad08f3915f9db6d550d215b3658c82eb38ceb2dff72cad1`
- 源码 JAR SHA256：`714bc9cebdba29d5e336e026367c50ff235bd0090e1949efcbd81537a213176e`
- AAR 与源码 JAR 均包含 `META-INF/androidx/webkit/webkit/LICENSE.txt`（Apache-2.0）。
  Chromium 边界源码的版权头另外指向 BSD-style LICENSE；完整条款和署名见后文。
- 已核对 AOSP 源码版权头：2018–2020、2022–2025。
  Chromium 源码版权头：2018–2020、2022–2025。

### 10. org.jetbrains.kotlin:kotlin-stdlib:1.7.10

- 主许可：Apache-2.0；`kotlin/util/MathJVM.kt` 中来源于 Boost 的特殊数学实现另适用
  Boost-1.0。作者/版权主体：JetBrains s.r.o.、Kotlin Programming Language contributors、
  Eric Ford、Hubert Holin。
- [固定 POM](https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/1.7.10/kotlin-stdlib-1.7.10.pom)
  · [官方源码 JAR](https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/1.7.10/kotlin-stdlib-1.7.10-sources.jar)
- POM SHA256：`6cc0cf5a2bc02dee060ebb90c3535fc3ddbd7a3bab210ace3e142aaf81764d81`
- 源码 JAR SHA256：`2176274ecf922fffdd9a7eeec18f5e3a69f7ed53dadb5add3c9a706560ac9d7f`
- 额外授权依据：[Kotlin v1.7.10 许可说明](https://github.com/JetBrains/kotlin/blob/v1.7.10/license/README.md)
  的 `libraries/stdlib/jvm/src/kotlin/util/MathJVM.kt` 条目，
  及 [固定 Boost 授权文本](https://github.com/JetBrains/kotlin/blob/v1.7.10/license/third_party/boost_LICENSE.txt)。
- Kotlin 编译器的 `license/NOTICE.txt` 明确适用于 Compiler distribution；本 APK
  没有 Kotlin 编译器，不把其 ASM、反射工具或测试数据许可误列为 stdlib 依赖。

### 11. org.jetbrains.kotlin:kotlin-stdlib-common:1.7.10

- 主许可：Apache-2.0；集合实现含 GWT 来源代码，无符号运算含 Guava 来源代码，
  两者也适用 Apache-2.0。版权主体：JetBrains s.r.o.、Kotlin Programming Language
  contributors、Google Inc.、The Guava Authors。
- [固定 POM](https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib-common/1.7.10/kotlin-stdlib-common-1.7.10.pom)
  · [官方源码 JAR](https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib-common/1.7.10/kotlin-stdlib-common-1.7.10-sources.jar)
- POM SHA256：`1011c63b88ee94cdff5d596937307559bc55037b733cc00ce63cda3cfae0a8eb`
- 源码 JAR SHA256：`a00a41d8900d12e097a9227454c593c843069def0e52c788a658f24fc3dccf2e`
- 已核对 `kotlin/collections/AbstractList.kt`、`AbstractMap.kt` 及 `kotlin/UnsignedUtils.kt`。
  对应上游：[GWT 许可](https://github.com/JetBrains/kotlin/blob/v1.7.10/license/third_party/gwt_license.txt)、
  [Guava 许可](https://github.com/JetBrains/kotlin/blob/v1.7.10/license/third_party/guava_license.txt)。
  完整 Apache 文本由上述共同文件携带，版权署名另见下方。

### 12. org.jetbrains:annotations:13.0

- 许可：Apache-2.0；版权主体：JetBrains s.r.o.、Sascha Weinreuter。
- [固定 POM](https://repo.maven.apache.org/maven2/org/jetbrains/annotations/13.0/annotations-13.0.pom)
  · [官方源码 JAR](https://repo.maven.apache.org/maven2/org/jetbrains/annotations/13.0/annotations-13.0-sources.jar)
- POM SHA256：`965aeb2bedff369819bdde1bf7a0b3b89b8247dd69c88b86375d76163bb8c397`
- 源码 JAR SHA256：`42a5e144b8e81d50d6913d1007b695e62e614705268d8cf9f13dbdc478c2c68e`
- 已核对 `org/intellij/lang/annotations/Identifier.java` 等文件的 Sascha Weinreuter
  Apache 头，以及 JetBrains 2000–2009、2000–2012、2000–2013 版权头。

### 13. org.jspecify:jspecify:1.0.0

- 许可：Apache-2.0；版权主体：The JSpecify Authors。
- [固定 POM](https://repo.maven.apache.org/maven2/org/jspecify/jspecify/1.0.0/jspecify-1.0.0.pom)
  · [官方源码 JAR](https://repo.maven.apache.org/maven2/org/jspecify/jspecify/1.0.0/jspecify-1.0.0-sources.jar)
- POM SHA256：`cdab929a3b95211f43d2090c5e2d0dfe8465960e378bc32b35841dab324433a6`
- 源码 JAR SHA256：`adf0898191d55937fb3192ba971826f4f294292c4a960740f3c27310e7b70296`
- 已核对版权头：`Copyright 2018-2020 The JSpecify Authors.`、
  `Copyright 2022 The JSpecify Authors.`。

## 保留的第三方署名

以下逐字保留已核对源码中的不同版权头，不把本项目作者替代为第三方作者。
逐文件原始署名仍可从上面固定版本源码 JAR 取得。
检查过的源码 JAR 没有单独 `NOTICE` 文件；WebKit 的嵌入许可文件已在上面注明。

### AndroidX / Android Open Source Project

```text
Copyright (C) 2009 The Android Open Source Project
Copyright (C) 2011 The Android Open Source Project
Copyright (C) 2012 The Android Open Source Project
Copyright (C) 2013 The Android Open Source Project
Copyright (C) 2014 The Android Open Source Project
Copyright (C) 2015 The Android Open Source Project
Copyright (C) 2016 The Android Open Source Project
Copyright (C) 2017 The Android Open Source Project
Copyright (C) 2018 The Android Open Source Project
Copyright (C) 2020 The Android Open Source Project
Copyright (C) 2021 The Android Open Source Project
Copyright (C) 2022 The Android Open Source Project
Copyright 2015 The Android Open Source Project
Copyright 2017 The Android Open Source Project
Copyright 2018 The Android Open Source Project
Copyright 2019 The Android Open Source Project
Copyright 2020 The Android Open Source Project
Copyright 2021 The Android Open Source Project
Copyright 2022 The Android Open Source Project
Copyright 2023 The Android Open Source Project
Copyright 2024 The Android Open Source Project
Copyright 2025 The Android Open Source Project
```

### Kotlin、GWT、Guava 与 JetBrains 注解

```text
Copyright 2010-2015 JetBrains s.r.o.
Copyright 2010-2016 JetBrains s.r.o.
Copyright 2010-2018 JetBrains s.r.o. and Kotlin Programming Language contributors.
Copyright 2010-2019 JetBrains s.r.o. and Kotlin Programming Language contributors.
Copyright 2010-2020 JetBrains s.r.o. and Kotlin Programming Language contributors.
Copyright 2010-2021 JetBrains s.r.o. and Kotlin Programming Language contributors.
Copyright 2010-2022 JetBrains s.r.o. and Kotlin Programming Language contributors.
Copyright 2007 Google Inc.
Copyright 2011 The Guava Authors
Copyright 2000-2009 JetBrains s.r.o.
Copyright 2000-2012 JetBrains s.r.o.
Copyright 2000-2013 JetBrains s.r.o.
Copyright 2006 Sascha Weinreuter
```

### JSpecify

```text
Copyright 2018-2020 The JSpecify Authors.
Copyright 2022 The JSpecify Authors.
```

## Chromium 边界代码：完整 BSD-3-Clause 文本

适用于 WebKit 源码 JAR 中的 `org/chromium/support_lib_boundary/**`。
该目录源码声明由 Chromium 的 BSD-style LICENSE 授权。
下方完整条款取自 [Chromium 官方 LICENSE](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/LICENSE)，
核验的 LICENSE Git blob 为 `2249a28657f86c645f8978b75babc1bd52aca318`。
这不表示本 APK 内含 Chromium 全部代码或依赖。

保留此版本组件中观察到的署名：

```text
Copyright 2018 The Chromium Authors
Copyright 2019 The Chromium Authors
Copyright 2020 The Chromium Authors
Copyright 2022 The Chromium Authors
Copyright 2023 The Chromium Authors
Copyright 2024 The Chromium Authors
Copyright 2025 The Chromium Authors
```

完整授权文本：

```text
Copyright 2015 The Chromium Authors

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

* Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
* Neither the name of Google LLC nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Kotlin 数学实现：完整 Boost-1.0 文本

适用于 `kotlin-stdlib:1.7.10` 中 `kotlin/util/MathJVM.kt` 的 Boost 来源部分。
授权依据：[固定版本 Kotlin 许可说明](https://github.com/JetBrains/kotlin/blob/v1.7.10/license/README.md)、
[固定版本 Boost 原文](https://github.com/JetBrains/kotlin/blob/v1.7.10/license/third_party/boost_LICENSE.txt)
（Git blob `127a5bc39ba030c7cb99cc0aedc4f280ffe27310`）。

```text
Copyright Eric Ford & Hubert Holin 2001.

Boost Software License - Version 1.0 - August 17th, 2003

Permission is hereby granted, free of charge, to any person or organization
obtaining a copy of the software and accompanying documentation covered by
this license (the "Software") to use, reproduce, display, distribute,
execute, and transmit the Software, and to prepare derivative works of the
Software, and to permit third-parties to whom the Software is furnished to
do so, all subject to the following:

The copyright notices in the Software and this entire statement, including
the above license grant, this restriction and the following disclaimer,
must be included in all copies of the Software, in whole or in part, and
all derivative works of the Software, unless such copies or derivative
works are solely in the form of machine-executable object code generated by
a source language processor.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, TITLE AND NON-INFRINGEMENT. IN NO EVENT
SHALL THE COPYRIGHT HOLDERS OR ANYONE DISTRIBUTING THE SOFTWARE BE LIABLE
FOR ANY DAMAGES OR OTHER LIABILITY, WHETHER IN CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

## 后续变更和验收要求

依赖坐标或版本变化时重新生成 runtime inventory，对比 POM、源码中的许可和署名，
并更新本清单。APK 验证应同时核对本文件、完整 Apache 文本和前端 MIT 文本实际存在。
本清单不能替代真机验收、漏洞审计或公开发布确认，也不扩展为构建工具、桌面、
Python 服务、Tailscale 或 Ollama 模型的统一许可证清单。
