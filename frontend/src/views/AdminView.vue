<template>
  <div class="admin-page">
    <!-- ── 顶部栏 ─────────────────────────────────────────── -->
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="16" height="16">
            <path
              d="M4 6.5A2.5 2.5 0 0 1 6.5 4H10l1.6 2H17.5A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-10Z"
              fill="currentColor"
            />
          </svg>
        </span>
        <div class="brand-text">
          <span class="brand-title">校园领域智能问答系统</span>
          <span class="brand-sub">知识库管理后台</span>
        </div>
      </div>

      <div class="topbar-right">
        <div class="user-chip">
          <span class="avatar">{{ userInitial }}</span>
          <div class="user-meta">
            <span class="user-name">{{ userLabel }}</span>
            <span class="user-role">管理员</span>
          </div>
        </div>
        <el-button text @click="$router.push('/')">返回对话</el-button>
        <el-button text @click="doLogout">退出</el-button>
      </div>
    </header>

    <div class="admin-body">
      <!-- ── 状态总览 ─────────────────────────────────────── -->
      <section class="hero">
        <div class="hero-left">
          <div class="health">
            <span class="dot" :class="syncOk ? 'ok' : 'warn'"></span>
            <span class="health-text">{{ syncText }}</span>
          </div>
          <h1 class="hero-title">知识库概览</h1>
          <p class="hero-desc">
            共 {{ overview.docs ?? '—' }} 份文档，
            {{ overview.active_docs ?? '—' }} 份生效；
            切分为 {{ overview.chunks ?? '—' }} 块，索引 {{ overview.index_size ?? '—' }} 个向量。
          </p>
        </div>
        <div class="hero-right">
          <el-button :loading="loading.overview" @click="refreshAll">
            <span class="btn-ico">↻</span> 刷新数据
          </el-button>
          <el-button type="primary" @click="scrollToImport">
            <span class="btn-ico">↑</span> 导入新语料
          </el-button>
        </div>
      </section>

      <!-- ── 指标卡 ───────────────────────────────────────── -->
      <section class="stat-grid">
        <div v-for="s in statCards" :key="s.key" class="stat-card" :class="s.tone">
          <div class="stat-ico" v-html="s.icon"></div>
          <div class="stat-body">
            <div class="stat-v">{{ s.value }}</div>
            <div class="stat-k">{{ s.label }}</div>
          </div>
          <div v-if="s.note" class="stat-note">{{ s.note }}</div>
        </div>
      </section>

      <!-- ── 语料导入 ─────────────────────────────────────── -->
      <section ref="importSection" class="card">
        <div class="card-head">
          <div class="card-title">
            <span class="sec-no">01</span>
            <h2>语料导入</h2>
          </div>
          <span class="hint">
            支持 {{ (config.supported_exts || []).join(' / ') }} ·
            单文件上限 {{ config.max_upload_mb || 40 }} MB
          </span>
        </div>

        <ol class="steps">
          <li
            v-for="(t, i) in STEP_TITLES"
            :key="t"
            class="step"
            :class="{ done: step > i, current: step === i }"
          >
            <span class="step-no">
              <template v-if="step > i">✓</template>
              <template v-else>{{ i + 1 }}</template>
            </span>
            <span class="step-t">{{ t }}</span>
            <span v-if="i < STEP_TITLES.length - 1" class="step-line"></span>
          </li>
        </ol>

        <!-- 步骤 1：上传 -->
        <div v-if="step === 0" class="step-body">
          <label class="drop" :class="{ filled: pickedFiles.length > 0 }">
            <input
              type="file"
              multiple
              class="drop-input"
              :accept="(config.supported_exts || []).join(',')"
              @change="onFileChange"
            />
            <span class="drop-ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="26" height="26">
                <path
                  d="M12 5v14M5 12h14"
                  stroke="currentColor" stroke-width="2" stroke-linecap="round"
                />
              </svg>
            </span>
            <span class="drop-main">
              {{
                pickedFiles.length === 0
                  ? '点击选择文件（可多选），或把文件拖到这里'
                  : pickedFiles.length === 1
                    ? pickedFiles[0].name
                    : `已选择 ${pickedFiles.length} 个文件`
              }}
            </span>
            <span class="drop-sub">
              {{
                pickedFiles.length === 0
                  ? '文件先进入暂存区，确认后才会加入知识库'
                  : `${formatSize(pickedTotalSize)} · 已就绪，等待上传`
              }}
            </span>
          </label>

          <!-- 多选时列出文件名，便于核对 -->
          <div v-if="pickedFiles.length > 1" class="picked-list">
            <div v-for="(f, i) in pickedFiles" :key="i" class="picked-row">
              <span class="picked-idx">{{ i + 1 }}</span>
              <span class="picked-name">{{ f.name }}</span>
              <span class="picked-size">{{ formatSize(f.size) }}</span>
            </div>
          </div>

          <div class="step-actions">
            <el-button v-if="pickedFiles.length" @click="pickedFiles = []">重新选择</el-button>
            <el-button
              type="primary"
              :disabled="!pickedFiles.length"
              :loading="loading.upload"
              @click="doUpload"
            >
              {{ pickedFiles.length > 1 ? `上传 ${pickedFiles.length} 个文件` : '上传并解析' }}
            </el-button>
          </div>
          <el-progress
            v-if="loading.upload && uploadPercent > 0"
            :percentage="uploadPercent"
            :stroke-width="6"
            class="up-progress"
          />
        </div>

        <!-- 步骤 2：核对 -->
        <div v-else-if="step === 1" class="step-body">
          <!-- ★ 批量模式：逐份列出解析与扫描结果 -->
          <template v-if="isBatch">
            <div class="scan-row">
              <span class="badge" :class="batchParsedAll ? 'ok' : 'primary'">
                <span class="badge-dot"></span>
                {{ batchParsedCount }} / {{ batchItems.length }} 份已解析
              </span>
              <span v-if="batchHighRiskCount" class="badge danger">
                <span class="badge-dot"></span>高风险 {{ batchHighRiskCount }} 份
              </span>
              <span v-if="batchFailedCount" class="badge warn">
                <span class="badge-dot"></span>解析失败 {{ batchFailedCount }} 份
              </span>
              <el-button
                size="small"
                text
                type="primary"
                :loading="loading.previewAll"
                @click="previewAllBatch"
              >
                重新解析全部
              </el-button>
            </div>

            <el-table :data="batchItems" size="small" max-height="360">
              <el-table-column label="#" width="46" align="center">
                <template #default="{ $index }">{{ $index + 1 }}</template>
              </el-table-column>
              <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
              <el-table-column label="大小" width="90">
                <template #default="{ row }">{{ formatSize(row.size) }}</template>
              </el-table-column>
              <el-table-column label="解析" width="150">
                <template #default="{ row }">
                  <el-tag v-if="row.parse_state === 'pending'" size="small" type="info" effect="plain">
                    待解析
                  </el-tag>
                  <el-tag v-else-if="row.parse_state === 'parsing'" size="small" effect="plain">
                    解析中…
                  </el-tag>
                  <el-tag v-else-if="row.parse_state === 'error'" size="small" type="danger" effect="plain">
                    失败
                  </el-tag>
                  <span v-else class="dim">{{ row.text_len }} 字 / {{ row.paragraph_count }} 段</span>
                </template>
              </el-table-column>
              <el-table-column label="敏感扫描" width="150">
                <template #default="{ row }">
                  <span v-if="row.parse_state !== 'done'" class="dim">—</span>
                  <span v-else-if="row.scan.block_count" class="badge danger">
                    <span class="badge-dot"></span>高风险 {{ row.scan.block_count }}
                  </span>
                  <span v-else-if="row.scan.warn_count" class="badge warn">
                    <span class="badge-dot"></span>中风险 {{ row.scan.warn_count }}
                  </span>
                  <span v-else class="badge ok"><span class="badge-dot"></span>干净</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120" align="right">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" @click="openDetail(row)">
                    详情
                  </el-button>
                  <el-button text type="danger" size="small" @click="removeBatchItem(row)">
                    移除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <div v-if="batchFailedCount" class="scan-box">
              <div class="scan-title danger">解析失败的文件（不会入库，可先移除）</div>
              <div v-for="(row, i) in batchItems.filter(r => r.parse_state === 'error')" :key="'e'+i"
                   class="scan-item">
                <code>{{ row.filename }}</code>
                <span class="ctx">{{ row.error }}</span>
              </div>
            </div>

            <div class="step-actions">
              <el-button @click="cancelFlow">取消</el-button>
              <el-button
                type="primary"
                :disabled="!batchImportableCount"
                @click="goToMetaStep"
              >
                下一步（{{ batchImportableCount }} 份待入库）
              </el-button>
            </div>
          </template>

          <!-- 单份模式 -->
          <template v-else>
          <el-alert
            v-if="preview.error"
            type="error"
            :closable="false"
            :title="preview.error"
            show-icon
          />
          <template v-else>
            <div class="scan-row">
              <span class="badge" :class="preview.scan.ok ? 'ok' : 'danger'">
                <span class="badge-dot"></span>
                {{ preview.scan.ok ? '未发现高风险敏感信息' : `发现 ${preview.scan.block_count} 处高风险` }}
              </span>
              <span v-if="preview.scan.warn_count" class="badge warn">
                <span class="badge-dot"></span>中风险 {{ preview.scan.warn_count }} 处
              </span>
              <span class="dim">
                {{ preview.text_len }} 字 / {{ preview.paragraph_count }} 段
                <template v-if="preview.table_count"> / {{ preview.table_count }} 个表格</template>
              </span>
            </div>

            <div v-if="preview.scan.block_count || preview.scan.warn_count" class="scan-box">
              <div v-if="preview.scan.block_count" class="scan-group">
                <div class="scan-title danger">高风险 · 请确认后再入库</div>
                <div v-for="(h, i) in preview.scan.blocks" :key="'b' + i" class="scan-item">
                  <el-tag size="small" type="danger" effect="plain">{{ h.rule }}</el-tag>
                  <code>{{ h.value }}</code>
                  <span class="ctx">{{ h.context }}</span>
                </div>
              </div>
              <div v-if="preview.scan.warn_count" class="scan-group">
                <div class="scan-title warn">中风险 · 多为办公信息，请复核</div>
                <div v-for="(h, i) in preview.scan.warns" :key="'w' + i" class="scan-item">
                  <el-tag size="small" type="warning" effect="plain">{{ h.rule }}</el-tag>
                  <code>{{ h.value }}</code>
                  <span class="ctx">{{ h.context }}</span>
                </div>
              </div>
            </div>

            <div class="sub-title">内容预览（前 1200 字）</div>
            <pre class="sample">{{ preview.sample }}</pre>

            <div class="step-actions">
              <el-button @click="cancelFlow">取消</el-button>
              <el-button type="primary" @click="goToMetaStep">内容无误，下一步</el-button>
            </div>
          </template>
          </template>
        </div>

        <!-- 步骤 3：元数据 -->
        <div v-else-if="step === 2" class="step-body">
          <!-- ★ 批量模式：每份文件一行，字段可就地编辑 -->
          <template v-if="isBatch">
            <div class="scan-row">
              <span class="badge primary">
                <span class="badge-dot"></span>{{ metaRows.length }} 份待入库
              </span>
              <span class="dim">
                已根据文件名预填，请核对；doc_id / 标题 / 族 ID / 版本为必填
              </span>
              <el-button size="small" text type="primary" @click="autoFillFamilyVersion">
                按 doc_id 自动补全族 ID 与版本
              </el-button>
            </div>

            <el-table :data="metaRows" size="small" max-height="420">
              <el-table-column label="#" width="46" align="center">
                <template #default="{ $index }">{{ $index + 1 }}</template>
              </el-table-column>
              <el-table-column label="文件" min-width="170" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="dim">{{ row.filename }}</span>
                </template>
              </el-table-column>
              <el-table-column label="文档 ID *" min-width="185">
                <template #default="{ row }">
                  <el-input v-model="row.doc_id" size="small" placeholder="pyfa_neteng_2025" />
                </template>
              </el-table-column>
              <el-table-column label="标题 *" min-width="200">
                <template #default="{ row }">
                  <el-input v-model="row.title" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="族 ID *" min-width="140">
                <template #default="{ row }">
                  <el-input v-model="row.family_id" size="small" placeholder="pyfa_neteng" />
                </template>
              </el-table-column>
              <el-table-column label="版本 *" width="100">
                <template #default="{ row }">
                  <el-input v-model="row.version" size="small" placeholder="2025" />
                </template>
              </el-table-column>
              <el-table-column label="生效日期" width="150">
                <template #default="{ row }">
                  <el-date-picker
                    v-model="row.effective_date" type="date" size="small"
                    value-format="YYYY-MM-DD" style="width: 100%" placeholder="可空"
                  />
                </template>
              </el-table-column>
              <el-table-column label="状态" width="118">
                <template #default="{ row }">
                  <el-select v-model="row.status" size="small">
                    <el-option label="active" value="active" />
                    <el-option label="inactive" value="inactive" />
                    <el-option label="draft" value="draft" />
                  </el-select>
                </template>
              </el-table-column>
            </el-table>

            <div v-if="metaRowsError" class="scan-box">
              <div class="scan-title danger">请先修正以下问题</div>
              <div v-for="(e, i) in metaRowsError" :key="'m'+i" class="scan-item">
                <code>{{ e.filename }}</code>
                <span class="ctx">{{ e.message }}</span>
              </div>
            </div>

            <div class="step-actions">
              <el-button @click="step = 1">上一步</el-button>
              <el-button type="primary" :loading="loading.confirm" @click="doConfirmBatch">
                确认入库 {{ metaRows.length }} 份
              </el-button>
            </div>
          </template>

          <!-- 单份模式 -->
          <template v-else>
          <el-form :model="meta" label-width="110px" label-position="top" class="meta-form">
            <el-row :gutter="18">
              <el-col :xs="24" :sm="12">
                <el-form-item label="文档 ID" required>
                  <el-input v-model="meta.doc_id" placeholder="如 pyfa_neteng_2025" />
                  <div class="field-hint">小写字母/数字/下划线，将作为 text/{doc_id}.txt</div>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="文档标题" required>
                  <el-input v-model="meta.title" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="文档族 ID" required>
                  <el-input v-model="meta.family_id" placeholder="如 pyfa_neteng" />
                  <div class="field-hint">同一文档的不同年份版本共用此 ID</div>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="版本" required>
                  <el-input v-model="meta.version" placeholder="如 2025" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="发布单位">
                  <el-input v-model="meta.issuer" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="状态">
                  <el-select v-model="meta.status" style="width: 100%">
                    <el-option label="active（生效）" value="active" />
                    <el-option label="inactive（失效）" value="inactive" />
                    <el-option label="draft（草稿）" value="draft" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="发布日期">
                  <el-date-picker
                    v-model="meta.publish_date" type="date"
                    value-format="YYYY-MM-DD" style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="生效日期">
                  <el-date-picker
                    v-model="meta.effective_date" type="date"
                    value-format="YYYY-MM-DD" style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="备注">
                  <el-input v-model="meta.notes" type="textarea" :rows="2" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="覆盖同名">
                  <el-switch v-model="meta.allow_overwrite" />
                  <span class="field-hint inline">覆盖已存在的 doc_id 或同名文件</span>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>

          <div class="step-actions">
            <el-button @click="step = 1">上一步</el-button>
            <el-button type="primary" :loading="loading.confirm" @click="doConfirm">
              确认入库
            </el-button>
          </div>
          </template>
        </div>

        <!-- 步骤 4：向量化 -->
        <div v-else class="step-body">
          <div v-if="confirmResult" class="done-banner">
            <span class="done-ico">✓</span>
            <div>
              <div class="done-title">已入库：{{ confirmResult.doc_id }}</div>
              <div class="done-desc">
                {{ confirmResult.text_len }} 字 · {{ confirmResult.paragraph_count }} 段 ·
                还需「向量化」才能被检索
              </div>
            </div>
          </div>

          <div v-if="pipelineLog.length" class="pipe-log">
            <div v-for="(l, i) in pipelineLog" :key="i" class="pipe-line">
              <span class="pipe-stage">{{ l.stage }}</span>
              <span class="pipe-msg">{{ l.message }}</span>
            </div>
          </div>

          <el-progress
            v-if="loading.pipeline || pipelineDone"
            :percentage="pipePercent"
            :stroke-width="8"
            :status="pipelineDone ? 'success' : ''"
          />

          <div class="step-actions">
            <el-button :disabled="loading.pipeline" @click="finishFlow">完成</el-button>
            <el-button
              v-if="!loading.pipeline && !pipelineDone"
              type="primary" @click="doPipeline"
            >
              开始向量化
            </el-button>
            <el-button v-if="pipelineDone" type="primary" @click="refreshAll">
              刷新概况
            </el-button>
          </div>
        </div>
      </section>

      <!-- ── 待处理文件 ───────────────────────────────────── -->
      <section v-if="stagingList.length" class="card">
        <div class="card-head">
          <div class="card-title">
            <span class="sec-no warn">!</span>
            <h2>待处理文件</h2>
          </div>
          <span class="hint">{{ stagingList.length }} 个文件尚未进入知识库</span>
        </div>
        <el-table :data="stagingList" size="small">
          <el-table-column prop="filename" label="文件名" min-width="240" />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ formatSize(row.size) }}</template>
          </el-table-column>
          <el-table-column prop="uploaded_at" label="上传时间" width="170" />
          <el-table-column label="操作" width="150" align="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="resumeStaging(row)">
                继续
              </el-button>
              <el-button text type="danger" size="small" @click="doDiscard(row)">
                丢弃
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <!-- ── 已入库文档 ───────────────────────────────────── -->
      <section class="card">
        <div class="card-head">
          <div class="card-title">
            <span class="sec-no">02</span>
            <h2>已入库文档</h2>
          </div>
          <span class="hint">共 {{ docs.length }} 份</span>
        </div>
        <el-table :data="docs" size="small" max-height="440">
          <template #empty>
            <div class="empty">
              <div class="empty-ico">◍</div>
              <div class="empty-t">知识库还是空的</div>
              <div class="empty-d">在上面「语料导入」里上传第一份文档</div>
            </div>
          </template>
          <el-table-column prop="doc_id" label="文档 ID" width="200">
            <template #default="{ row }">
              <code class="mono">{{ row.doc_id }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
          <el-table-column prop="family_id" label="族" width="140" show-overflow-tooltip />
          <el-table-column prop="version" label="版本" width="72" align="center" />
          <el-table-column label="状态" width="86" align="center">
            <template #default="{ row }">
              <span class="badge" :class="row.status === 'active' ? 'ok' : 'muted'">
                <span class="badge-dot"></span>{{ row.status }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="字数" width="90" align="right">
            <template #default="{ row }">{{ formatNum(row.chars) }}</template>
          </el-table-column>
          <el-table-column label="文件" width="130" align="center">
            <template #default="{ row }">
              <span class="file-chip" :class="row.raw_exists ? 'ok' : 'err'">
                原文{{ row.raw_exists ? '✓' : '✗' }}
              </span>
              <span class="file-chip" :class="row.text_exists ? 'ok' : 'err'">
                文本{{ row.text_exists ? '✓' : '✗' }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <!-- ── 导入记录 ─────────────────────────────────────── -->
      <section class="card">
        <div class="card-head">
          <div class="card-title">
            <span class="sec-no">03</span>
            <h2>导入记录</h2>
          </div>
          <span class="hint">最近 {{ imports.length }} 条</span>
        </div>
        <el-table :data="imports" size="small" max-height="320">
          <template #empty>
            <div class="empty">
              <div class="empty-ico">◍</div>
              <div class="empty-t">还没有导入记录</div>
              <div class="empty-d">通过本页导入语料后，这里会留下操作与结果</div>
            </div>
          </template>
          <el-table-column prop="doc_id" label="文档 ID" width="200">
            <template #default="{ row }">
              <code class="mono">{{ row.doc_id || '—' }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="source_name" label="源文件" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态" width="150" align="center">
            <template #default="{ row }">
              <span class="badge" :class="statusTone(row.status)">
                <span class="badge-dot"></span>{{ statusLabel(row.status) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
          <el-table-column prop="updated_at" label="时间" width="170">
            <template #default="{ row }">{{ shortTime(row.updated_at) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <footer class="page-foot">
        校园领域智能问答系统 · 管理后台　|　
        索引目录 {{ config.index_dir || '—' }}　|　
        {{ shortTime(overview.index_built_at) }} 建索引
        <template v-if="overview.index_build_seconds">
          （耗时 {{ overview.index_build_seconds }}s）
        </template>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchMe, logout } from '../api/auth'
import { useRouter } from 'vue-router'
import {
  confirmImport, discardStaging, fetchAdminConfig, fetchAdminDocs,
  fetchAdminOverview, fetchImports, fetchPreview, fetchStaging,
  formatSize, runPipelineStream, uploadCorpus, uploadCorpusBatch,
} from '../api/admin'

const router = useRouter()
const STEP_TITLES = ['上传文件', '核对内容', '填写元数据', '向量化']
const STAGE_PERCENT = { chunk: 35, index: 85, reload: 95, pipeline: 100 }

const overview = ref({})
const docs = ref([])
const imports = ref([])
const stagingList = ref([])
const config = ref({ supported_exts: [], max_upload_mb: 40 })
const currentUser = ref(null)
const importSection = ref(null)

const step = ref(0)
// 支持多选：单份走原有流程，多份走批量流程
const pickedFiles = ref([])
const pickedTotalSize = computed(() =>
  pickedFiles.value.reduce((s, f) => s + (f.size || 0), 0))
const uploadPercent = ref(0)
const preview = reactive({ scan: {}, sample: '', text_len: 0, paragraph_count: 0 })
const meta = reactive({
  doc_id: '', title: '', family_id: '', version: '', issuer: '',
  publish_date: '', effective_date: '', expire_date: '', source_url: '',
  file_type: 'txt', status: 'active', notes: '', allow_overwrite: false,
})
const stagingId = ref('')

/* ── 批量导入状态 ─────────────────────────────────────── */
const batchItems = ref([])          // 上传后的文件行（含解析与扫描结果、元数据）
const batchResult = ref(null)       // 批量入库结果 {ok, failed}
const metaRowsError = ref([])       // 元数据校验失败清单
const detailVisible = ref(false)
const detailRow = ref(null)
const isBatch = computed(() => batchItems.value.length > 0)
const batchParsedCount = computed(() =>
  batchItems.value.filter((r) => r.parse_state === 'done').length)
const batchParsedAll = computed(() =>
  batchItems.value.length > 0 && batchParsedCount.value === batchItems.value.length)
const batchHighRiskCount = computed(() =>
  batchItems.value.filter((r) => (r.scan?.block_count || 0) > 0).length)
const batchFailedCount = computed(() =>
  batchItems.value.filter((r) => r.parse_state === 'error').length)
const batchImportableCount = computed(() =>
  batchItems.value.filter((r) => r.parse_state === 'done').length)
/** 可入库的行 → 元数据表格数据源 */
const metaRows = computed(() =>
  batchItems.value.filter((r) => r.parse_state === 'done'))

const confirmResult = ref(null)
const pipelineLog = ref([])
const pipePercent = ref(0)
const pipelineDone = ref(false)
const loading = reactive({ overview: false, upload: false, confirm: false,
                           pipeline: false, previewAll: false })

/* ── 计算属性 ─────────────────────────────────────────── */
const userLabel = computed(() => currentUser.value?.display_name
  || currentUser.value?.username || '管理员')
const userInitial = computed(() => (userLabel.value || '管').slice(0, 1).toUpperCase())

/** 语料份数与索引块数是否一致（不一致通常意味着有文档未向量化） */
const syncOk = computed(() => {
  const c = overview.value.chunks
  const i = overview.value.index_size
  return c !== undefined && i !== undefined ? c === i : true
})
const syncText = computed(() => {
  if (overview.value.staging_pending > 0) {
    return `有 ${overview.value.staging_pending} 个文件待处理`
  }
  return syncOk.value ? '知识库与索引一致' : '索引与切分块数不一致，建议重新向量化'
})

const ICONS = {
  docs: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M6 3h8l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M14 3v5h5" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>',
  active: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M20 6 9 17l-5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  chunks: '<svg viewBox="0 0 24 24" width="18" height="18"><rect x="3" y="4" width="7" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="14" y="4" width="7" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="3" y="14" width="7" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="14" y="14" width="7" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>',
  text: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M5 6h14M5 11h14M5 16h9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  index: '<svg viewBox="0 0 24 24" width="18" height="18"><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="4" r="2" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="20" r="2" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="4" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="20" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
  staging: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M12 3v12m0 0 4-4m-4 4-4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
}

const statCards = computed(() => {
  const o = overview.value
  return [
    { key: 'docs', label: '文档份数', value: o.docs ?? '—', tone: 'primary', icon: ICONS.docs },
    { key: 'active', label: '生效文档', value: o.active_docs ?? '—', tone: 'success', icon: ICONS.active },
    { key: 'chunks', label: '切分块数', value: o.chunks ?? '—', tone: 'info', icon: ICONS.chunks },
    { key: 'text', label: '语料字数', value: formatNum(o.text_chars), tone: 'info', icon: ICONS.text },
    {
      key: 'index', label: '索引向量数', value: o.index_size ?? '—',
      tone: syncOk.value ? 'info' : 'warn', icon: ICONS.index,
      note: syncOk.value ? '' : '与块数不一致',
    },
    {
      key: 'staging', label: '待处理上传', value: o.staging_pending ?? 0,
      tone: o.staging_pending > 0 ? 'warn' : 'muted', icon: ICONS.staging,
      note: o.staging_pending > 0 ? '需要处理' : '',
    },
  ]
})

/* ── 工具函数 ─────────────────────────────────────────── */
function formatNum(n) {
  if (n === null || n === undefined) return '—'
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n)
}
function shortTime(t) {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 19)
}
function statusTone(s) {
  if (s === 'pipeline_ok' || s === 'imported') return 'ok'
  if (s === 'failed') return 'danger'
  if (s === 'pipeline_running') return 'primary'
  return 'muted'
}
function statusLabel(s) {
  return {
    imported: '已入库', pipeline_running: '向量化中', pipeline_ok: '已完成',
    failed: '失败', pending: '待确认',
  }[s] || s
}
function scrollToImport() {
  importSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ── 数据加载 ─────────────────────────────────────────── */
async function refreshAll() {
  loading.overview = true
  try {
    const [ov, dc, im, st] = await Promise.all([
      fetchAdminOverview(), fetchAdminDocs(), fetchImports(), fetchStaging(),
    ])
    overview.value = ov
    docs.value = dc
    imports.value = im
    stagingList.value = st
  } catch (e) {
    ElMessage.error('加载管理数据失败')
  } finally {
    loading.overview = false
  }
}

function onFileChange(e) {
  const list = Array.from(e.target.files || [])
  if (list.length) {
    pickedFiles.value = list
    uploadPercent.value = 0
  }
}

function applySuggestion(pv) {
  const sug = pv.suggested_doc_id || ''
  const m = sug.match(/^(.*?)_?(\d{4})$/)
  Object.assign(preview, pv)
  Object.assign(meta, {
    doc_id: sug,
    title: pv.suggested_title || '',
    family_id: m ? m[1] : sug,
    version: m ? m[2] : '',
    file_type: pv.file_type || 'txt',
  })
}

/** 从建议的 doc_id 拆出族 ID 与版本（批量的每行预填用） */
function splitDocId(sug) {
  const m = String(sug || '').match(/^(.*?)_?(\d{4})$/)
  return m ? { family_id: m[1], version: m[2] } : { family_id: sug || '', version: '' }
}

async function doUpload() {
  if (!pickedFiles.value.length) return
  const files = pickedFiles.value
  loading.upload = true
  try {
    if (files.length === 1) {
      // 单份：沿用原流程（上传即解析，直接进核对）
      const res = await uploadCorpus(files[0], (p) => { uploadPercent.value = p })
      stagingId.value = res.staging_id
      applySuggestion(await fetchPreview(res.staging_id))
      batchItems.value = []
      step.value = 1
      return
    }

    // 多份：批量落盘（本接口不解析），随后逐份解析
    const res = await uploadCorpusBatch(files, (p) => { uploadPercent.value = p })
    batchItems.value = res.items.map((it) => ({
      staging_id: it.staging_id || '',
      filename: it.filename,
      size: it.size || 0,
      ok: !!it.ok,
      error: it.error || '',
      parse_state: it.ok ? 'pending' : 'error',
      text_len: 0,
      paragraph_count: 0,
      table_count: 0,
      sample: '',
      scan: {},
      // 元数据字段（解析后用建议值预填，管理员可就地改）
      doc_id: '', title: '', family_id: '', version: '',
      issuer: '', publish_date: '', effective_date: '', expire_date: '',
      source_url: '', file_type: it.ext || '', status: 'active', notes: '',
    }))
    if (res.ok_count === 0) {
      ElMessage.error('全部文件上传失败，请检查格式与大小')
    } else {
      ElMessage.success(`已上传 ${res.ok_count} / ${res.total} 个文件，正在解析…`)
    }
    step.value = 1
    await previewAllBatch()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '上传失败')
  } finally {
    loading.upload = false
  }
}

/** 批量：逐份解析 + 敏感扫描（串行，避免同时打满 CPU/GPU） */
async function previewAllBatch() {
  loading.previewAll = true
  const rows = batchItems.value.filter((r) => r.ok)
  try {
    for (const row of rows) {
      row.parse_state = 'parsing'
      try {
        const pv = await fetchPreview(row.staging_id)
        Object.assign(row, {
          text_len: pv.text_len,
          paragraph_count: pv.paragraph_count,
          table_count: pv.table_count,
          sample: pv.sample,
          scan: pv.scan || {},
          file_type: pv.file_type || row.file_type,
          doc_id: pv.suggested_doc_id || row.doc_id,
          title: pv.suggested_title || row.title,
          ...splitDocId(pv.suggested_doc_id),
          parse_state: pv.error ? 'error' : 'done',
          error: pv.error || '',
        })
      } catch (e) {
        row.parse_state = 'error'
        row.error = e.response?.data?.detail || e.message || '解析失败'
      }
    }
  } finally {
    loading.previewAll = false
  }
}

/** 按 doc_id 重新推导族 ID 与版本（管理员改了 doc_id 后可一键同步） */
function autoFillFamilyVersion() {
  metaRows.value.forEach((row) => {
    const { family_id, version } = splitDocId(row.doc_id)
    if (family_id) row.family_id = family_id
    if (version) row.version = version
  })
  ElMessage.success('已按文档 ID 补全族 ID 与版本')
}

/** 进入元数据步骤：单份走原逻辑，多份准备表格数据 */
function goToMetaStep() {
  if (isBatch.value) {
    const rows = metaRows.value.filter((r) => r.doc_id)
    if (rows.length !== metaRows.value.length) {
      ElMessage.error('每份文件都需要文档 ID')
      return
    }
  }
  step.value = 2
}

function removeBatchItem(row) {
  const i = batchItems.value.indexOf(row)
  if (i >= 0) batchItems.value.splice(i, 1)
  if (!batchItems.value.length) {
    resetFlow()
  }
}

function openDetail(row) {
  Object.assign(preview, {
    filename: row.filename,
    text_len: row.text_len,
    paragraph_count: row.paragraph_count,
    table_count: row.table_count,
    sample: row.sample,
    scan: row.scan || {},
    error: row.error || '',
  })
  detailRow.value = row
  detailVisible.value = true
}

/** 批量确认入库（逐份提交；单份失败不影响其余；最后统一跑一次向量化） */
async function doConfirmBatch() {
  const rows = metaRows.value
  const bad = []
  rows.forEach((r) => {
    if (!r.doc_id || !r.title || !r.family_id || !r.version) {
      bad.push({ filename: r.filename, message: '文档 ID / 标题 / 族 ID / 版本 为必填' })
    }
  })
  if (bad.length) {
    metaRowsError.value = bad
    ElMessage.error(`有 ${bad.length} 份信息不完整`)
    return
  }
  metaRowsError.value = []
  loading.confirm = true
  const done = []
  const failed = []
  try {
    for (const r of rows) {
      try {
        const res = await confirmImport(r.staging_id, {
          doc_id: r.doc_id, title: r.title, family_id: r.family_id,
          version: r.version, issuer: r.issuer || '',
          publish_date: r.publish_date || '', effective_date: r.effective_date || '',
          expire_date: r.expire_date || '', source_url: r.source_url || '',
          file_type: r.file_type || 'txt', status: r.status || 'active',
          notes: r.notes || '', allow_overwrite: false,
        })
        done.push(res)
      } catch (e) {
        failed.push({
          filename: r.filename,
          message: e.response?.data?.detail || e.message || '入库失败',
        })
      }
    }
    batchResult.value = { ok: done.length, failed }
    if (done.length) {
      confirmResult.value = {
        import_id: done[done.length - 1].import_id,
        doc_id: done.length === 1 ? done[0].doc_id : `${done.length} 份文档`,
        text_len: done.reduce((s, d) => s + (d.text_len || 0), 0),
        paragraph_count: done.reduce((s, d) => s + (d.paragraph_count || 0), 0),
        message: '已入库；请继续执行向量化以使其可被检索',
      }
      step.value = 3
      pipelineLog.value = []
      pipelineDone.value = false
      pipePercent.value = 0
    }
    if (failed.length) {
      metaRowsError.value = failed
      ElMessage.warning(`成功 ${done.length} 份，失败 ${failed.length} 份`)
    } else {
      ElMessage.success(`已入库 ${done.length} 份`)
    }
    await refreshAll()
  } finally {
    loading.confirm = false
  }
}

async function doConfirm() {
  if (!meta.doc_id || !meta.title || !meta.family_id || !meta.version) {
    ElMessage.warning('请填写文档 ID、标题、族 ID、版本')
    return
  }
  loading.confirm = true
  try {
    confirmResult.value = await confirmImport(stagingId.value, { ...meta })
    step.value = 3
    pipelineLog.value = []
    pipelineDone.value = false
    pipePercent.value = 0
    await refreshAll()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '入库失败')
  } finally {
    loading.confirm = false
  }
}

async function doPipeline() {
  loading.pipeline = true
  pipelineLog.value = []
  pipePercent.value = 0
  pipelineDone.value = false
  try {
    await runPipelineStream({
      importId: confirmResult.value?.import_id,
      onEvent: (ev) => {
        if (ev.message) {
          pipelineLog.value.push({ stage: ev.stage || ev.event || '-', message: ev.message })
        }
        if (ev.status === 'done' && STAGE_PERCENT[ev.stage] !== undefined) {
          pipePercent.value = STAGE_PERCENT[ev.stage]
        }
        if (ev.event === 'error') ElMessage.error(ev.message || '流水线失败')
      },
    })
    pipePercent.value = 100
    pipelineDone.value = true
    ElMessage.success('向量化完成，新语料已可被检索')
    await refreshAll()
  } catch (e) {
    ElMessage.error(e.message || '流水线执行失败')
  } finally {
    loading.pipeline = false
  }
}

function cancelFlow() {
  step.value = 0
  pickedFiles.value = []
  uploadPercent.value = 0
}
function resetFlow() {
  cancelFlow()
  batchItems.value = []
  batchResult.value = null
  metaRowsError.value = []
  confirmResult.value = null
  pipelineLog.value = []
  pipePercent.value = 0
  pipelineDone.value = false
  stagingId.value = ''
}
async function finishFlow() {
  resetFlow()
  await refreshAll()
}

async function resumeStaging(row) {
  stagingId.value = row.staging_id
  try {
    applySuggestion(await fetchPreview(row.staging_id))
    step.value = 1
    scrollToImport()
  } catch (e) {
    ElMessage.error('解析失败')
  }
}

async function doDiscard(row) {
  try {
    await ElMessageBox.confirm(`确定丢弃「${row.filename}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await discardStaging(row.staging_id)
    ElMessage.success('已丢弃')
    await refreshAll()
  } catch (e) {
    ElMessage.error('丢弃失败')
  }
}

async function doLogout() {
  try {
    await logout()
  } finally {
    router.push('/login')
  }
}

onMounted(async () => {
  try { currentUser.value = await fetchMe() } catch { /* 仅影响显示 */ }
  try { config.value = await fetchAdminConfig() } catch { /* 不影响主流程 */ }
  await refreshAll()
})
</script>

<style scoped>
/* ── 页面骨架 ─────────────────────────────────────────── */
.admin-page {
  min-height: 100vh;
  background: var(--c-bg-page);
}
.topbar {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-5);
  background: var(--c-bg-card);
  border-bottom: 1px solid var(--c-border);
  box-shadow: var(--sh-1);
  position: sticky;
  top: 0;
  z-index: 20;
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: var(--r-md);
  background: var(--c-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}
.brand-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
}
.brand-sub {
  font-size: 11px;
  color: var(--c-text-3);
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.user-chip {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px 10px 4px 4px;
  border: 1px solid var(--c-border);
  border-radius: 999px;
}
.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--c-primary-light);
  color: var(--c-primary-dark);
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.user-name {
  font-size: 12px;
  color: var(--c-text-1);
  font-weight: 600;
}
.user-role {
  font-size: 10px;
  color: var(--c-text-3);
}

.admin-body {
  max-width: 1120px;
  margin: 0 auto;
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

/* ── 状态总览 ─────────────────────────────────────────── */
.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-5);
  flex-wrap: wrap;
}
.health {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  font-size: 12px;
  color: var(--c-text-2);
  margin-bottom: var(--sp-2);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot.ok {
  background: var(--c-success);
  box-shadow: 0 0 0 3px var(--c-success-bg);
}
.dot.warn {
  background: var(--c-warn);
  box-shadow: 0 0 0 3px var(--c-warn-bg);
}
.hero-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 650;
  color: var(--c-text-1);
  letter-spacing: 0.2px;
}
.hero-desc {
  margin: 0;
  font-size: 13px;
  color: var(--c-text-3);
  line-height: 1.6;
}
.hero-right {
  display: flex;
  gap: var(--sp-2);
  padding-top: 22px;
}
.btn-ico {
  display: inline-block;
  margin-right: 3px;
  font-weight: 700;
}

/* ── 指标卡 ───────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--sp-3);
}
.stat-card {
  position: relative;
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  padding: var(--sp-4) var(--sp-3) var(--sp-3);
  box-shadow: var(--sh-1);
  transition: box-shadow 0.16s, transform 0.16s;
}
.stat-card:hover {
  box-shadow: var(--sh-2);
  transform: translateY(-1px);
}
/* 顶部 3px 实色条（非渐变）区分语义 */
.stat-card::before {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  top: 0;
  height: 3px;
  border-radius: 0 0 3px 3px;
  background: var(--accent, var(--c-border));
}
.stat-card.primary { --accent: #409eff; --tint: #ecf5ff; --ink: #337ecc; }
.stat-card.success { --accent: #00b42a; --tint: #e8ffea; --ink: #009a29; }
.stat-card.info    { --accent: #86909c; --tint: #f2f3f5; --ink: #4e5969; }
.stat-card.warn    { --accent: #ff7d00; --tint: #fff7e8; --ink: #d96a00; }
.stat-card.muted   { --accent: #c9cdd4; --tint: #f7f8fa; --ink: #86909c; }

.stat-ico {
  width: 32px;
  height: 32px;
  border-radius: var(--r-md);
  background: var(--tint, var(--c-bg-hover));
  color: var(--ink, var(--c-text-2));
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--sp-2);
}
.stat-v {
  font-size: 22px;
  font-weight: 650;
  color: var(--c-text-1);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.stat-k {
  font-size: 12px;
  color: var(--c-text-3);
  margin-top: 1px;
}
.stat-note {
  margin-top: 5px;
  font-size: 11px;
  color: var(--accent);
  font-weight: 600;
}

/* ── 卡片与标题 ───────────────────────────────────────── */
.card {
  background: var(--c-bg-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  padding: var(--sp-5);
  box-shadow: var(--sh-1);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
  flex-wrap: wrap;
}
.card-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.card-title h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text-1);
}
.sec-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--r-sm);
  background: var(--c-primary-light);
  color: var(--c-primary-dark);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.4px;
}
.sec-no.warn {
  background: var(--c-warn-bg);
  color: var(--c-warn);
}
.hint {
  font-size: 12px;
  color: var(--c-text-3);
}

/* ── 步骤条（自绘，无渐变）───────────────────────────── */
.steps {
  display: flex;
  align-items: center;
  list-style: none;
  margin: 0 0 var(--sp-5);
  padding: 0;
  gap: 0;
}
.step {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: 1;
  min-width: 0;
}
.step:last-child {
  flex: 0 0 auto;
}
.step-no {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1.5px solid var(--c-border-strong);
  color: var(--c-text-3);
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--c-bg-card);
  transition: all 0.18s;
}
.step-t {
  font-size: 13px;
  color: var(--c-text-3);
  white-space: nowrap;
}
.step-line {
  flex: 1;
  height: 1.5px;
  background: var(--c-border);
  margin: 0 var(--sp-3);
  border-radius: 2px;
}
.step.current .step-no {
  border-color: var(--c-primary);
  background: var(--c-primary);
  color: #fff;
}
.step.current .step-t {
  color: var(--c-text-1);
  font-weight: 600;
}
.step.done .step-no {
  border-color: var(--c-success);
  background: var(--c-success-bg);
  color: var(--c-success);
}
.step.done .step-t {
  color: var(--c-text-2);
}
.step.done .step-line {
  background: var(--c-success);
  opacity: 0.4;
}

/* ── 上传区 ───────────────────────────────────────────── */
.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: var(--sp-6) var(--sp-4);
  border: 1.5px dashed var(--c-border-strong);
  border-radius: var(--r-lg);
  background: var(--c-bg-page);
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s;
  position: relative;
}
.drop:hover {
  border-color: var(--c-primary);
  background: var(--c-primary-light);
}
.drop.filled {
  border-style: solid;
  border-color: var(--c-primary-border);
  background: var(--c-primary-light);
}
.drop-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
.drop-ico {
  color: var(--c-primary);
  display: flex;
}
.drop-main {
  font-size: 14px;
  color: var(--c-text-1);
  font-weight: 600;
  word-break: break-all;
  text-align: center;
}
.drop-sub {
  font-size: 12px;
  color: var(--c-text-3);
}
.step-body {
  padding-top: var(--sp-1);
}
.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}
.up-progress {
  margin-top: var(--sp-3);
}
/* 多选文件列表 */
.picked-list {
  margin-top: var(--sp-3);
  max-height: 200px;
  overflow: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background: var(--c-bg-page);
}
.picked-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 5px var(--sp-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--c-border);
}
.picked-row:last-child {
  border-bottom: none;
}
.picked-idx {
  width: 20px;
  color: var(--c-text-4);
  font-size: 11px;
  text-align: right;
  flex-shrink: 0;
}
.picked-row .picked-name {
  flex: 1;
  min-width: 0;
  color: var(--c-text-2);
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.picked-row .picked-size {
  flex: 0 0 auto;
  color: var(--c-text-3);
  font-size: 12px;
}

/* ── 徽标 ─────────────────────────────────────────────── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid transparent;
  white-space: nowrap;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.badge.ok {
  background: var(--c-success-bg);
  color: #009a29;
  border-color: #b7f0c0;
}
.badge.warn {
  background: var(--c-warn-bg);
  color: #d96a00;
  border-color: var(--c-warn-border);
}
.badge.danger {
  background: var(--c-danger-bg);
  color: var(--c-danger);
  border-color: #ffc9c0;
}
.badge.primary {
  background: var(--c-primary-light);
  color: var(--c-primary-dark);
  border-color: var(--c-primary-border);
}
.badge.muted {
  background: var(--c-bg-hover);
  color: var(--c-text-3);
  border-color: var(--c-border);
}

/* ── 扫描结果 ─────────────────────────────────────────── */
.scan-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}
.scan-row .dim {
  font-size: 12px;
  color: var(--c-text-3);
  margin-left: auto;
}
.scan-box {
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-4);
  background: #fffdf8;
}
.scan-group + .scan-group {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--c-border);
}
.scan-title {
  font-size: 12px;
  font-weight: 700;
  margin-bottom: var(--sp-2);
  letter-spacing: 0.2px;
}
.scan-title.danger {
  color: var(--c-danger);
}
.scan-title.warn {
  color: var(--c-warn);
}
.scan-item {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  padding: 3px 0;
  font-size: 12px;
  flex-wrap: wrap;
}
.scan-item code {
  background: var(--c-bg-hover);
  padding: 1px 6px;
  border-radius: var(--r-sm);
  color: var(--c-danger);
  font-size: 12px;
}
.scan-item .ctx {
  color: var(--c-text-3);
  font-size: 11px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--c-text-2);
  margin-bottom: var(--sp-2);
  letter-spacing: 0.2px;
}
.sample {
  max-height: 260px;
  overflow: auto;
  background: var(--c-bg-page);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: var(--sp-4);
  font-size: 13px;
  line-height: 1.8;
  color: var(--c-text-2);
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
}
.field-hint {
  font-size: 11px;
  color: var(--c-text-3);
  line-height: 1.5;
  margin-top: 2px;
}
.field-hint.inline {
  margin-left: var(--sp-3);
}

/* ── 完成横幅 ─────────────────────────────────────────── */
.done-banner {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  border-radius: var(--r-md);
  background: var(--c-success-bg);
  border: 1px solid #b7f0c0;
}
.done-ico {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--c-success);
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.done-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
}
.done-desc {
  font-size: 12px;
  color: var(--c-text-2);
  margin-top: 2px;
}

/* ── 流水线日志 ───────────────────────────────────────── */
.pipe-log {
  max-height: 220px;
  overflow: auto;
  background: var(--c-bg-page);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  margin: var(--sp-3) 0;
  font-size: 12.5px;
}
.pipe-line {
  display: flex;
  gap: var(--sp-3);
  padding: 2px 0;
}
.pipe-stage {
  width: 68px;
  flex-shrink: 0;
  color: var(--c-primary-dark);
  font-weight: 600;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11.5px;
}
.pipe-msg {
  color: var(--c-text-2);
}

/* ── 表格与空状态 ─────────────────────────────────────── */
.mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  color: var(--c-text-2);
  background: var(--c-bg-page);
  padding: 1px 6px;
  border-radius: var(--r-sm);
}
.file-chip {
  font-size: 11px;
  margin-right: 5px;
  white-space: nowrap;
}
.file-chip.ok {
  color: var(--c-success);
}
.file-chip.err {
  color: var(--c-danger);
}
.empty {
  padding: var(--sp-5) 0;
  text-align: center;
}
.empty-ico {
  font-size: 26px;
  color: var(--c-text-4);
  line-height: 1;
}
.empty-t {
  margin-top: 6px;
  font-size: 14px;
  color: var(--c-text-2);
  font-weight: 600;
}
.empty-d {
  margin-top: 2px;
  font-size: 12px;
  color: var(--c-text-3);
}

.page-foot {
  text-align: center;
  font-size: 11.5px;
  color: var(--c-text-4);
  padding: var(--sp-2) 0 var(--sp-5);
  line-height: 1.8;
}

/* ── 响应式 ───────────────────────────────────────────── */
@media (max-width: 1060px) {
  .stat-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 720px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .hero-right {
    padding-top: 0;
  }
  .step-t {
    display: none;
  }
  .step-line {
    margin: 0 var(--sp-2);
  }
  .user-meta {
    display: none;
  }
}
</style>
