import {
  blob,
  index,
  integer,
  primaryKey,
  real,
  sqliteTable,
  text,
  uniqueIndex,
} from 'drizzle-orm/sqlite-core';

export const projects = sqliteTable('projects', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  description: text('description').notNull().default(''),
  dataPolicy: text('data_policy').notNull().default('local_only'),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
});

export const sources = sqliteTable(
  'sources',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    kind: text('kind').notNull(),
    uri: text('uri'),
    revision: text('revision'),
    metadata: text('metadata_json').notNull().default('{}'),
    createdAt: text('created_at').notNull(),
  },
  (table) => [index('idx_sources_project_id').on(table.projectId)],
);

export const assets = sqliteTable(
  'assets',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    sourceId: text('source_id').references(() => sources.id),
    sha256: text('sha256').notNull(),
    originalFilename: text('original_filename').notNull(),
    mediaType: text('media_type').notNull(),
    objectKey: text('object_key').notNull(),
    byteSize: integer('byte_size').notNull(),
    status: text('status').notNull().default('active'),
    qualityScore: real('quality_score'),
    metadata: text('metadata_json').notNull().default('{}'),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_assets_project_media').on(table.projectId, table.mediaType),
    index('idx_assets_sha256').on(table.sha256),
    index('idx_assets_project_status').on(table.projectId, table.status),
  ],
);

export const contentUnits = sqliteTable(
  'content_units',
  {
    id: text('id').primaryKey(),
    assetId: text('asset_id')
      .notNull()
      .references(() => assets.id),
    kind: text('kind').notNull(),
    locator: text('locator_json').notNull().default('{}'),
    textContent: text('text_content'),
    parentId: text('parent_id'),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_content_units_asset_id').on(table.assetId),
    index('idx_content_units_asset_kind').on(table.assetId, table.kind),
  ],
);

export const jobs = sqliteTable(
  'jobs',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    kind: text('kind').notNull(),
    state: text('state').notNull(),
    profile: text('profile').notNull().default('balanced'),
    processorId: text('processor_id').notNull().default('core.identity'),
    processorVersion: text('processor_version').notNull().default('1.0.0'),
    deterministic: integer('deterministic', { mode: 'boolean' })
      .notNull()
      .default(true),
    cacheable: integer('cacheable', { mode: 'boolean' })
      .notNull()
      .default(true),
    modelRevision: text('model_revision'),
    parameters: text('parameters_json').notNull().default('{}'),
    resourceHints: text('resource_hints_json').notNull().default('{}'),
    totalItems: integer('total_items').notNull().default(0),
    processedCount: integer('processed_count').notNull().default(0),
    failedCount: integer('failed_count').notNull().default(0),
    skippedCount: integer('skipped_count').notNull().default(0),
    cachedCount: integer('cached_count').notNull().default(0),
    progress: integer('progress').notNull().default(0),
    checkpoint: text('checkpoint_json').notNull().default('{}'),
    leaseOwner: text('lease_owner'),
    leaseExpiresAt: text('lease_expires_at'),
    errorSummary: text('error_summary'),
    lastError: text('last_error'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
    startedAt: text('started_at'),
    completedAt: text('completed_at'),
  },
  (table) => [
    index('idx_jobs_project_state').on(table.projectId, table.state),
    index('idx_jobs_claimable').on(table.state, table.createdAt),
  ],
);

export const jobItems = sqliteTable(
  'job_items',
  {
    id: text('id').primaryKey(),
    jobId: text('job_id')
      .notNull()
      .references(() => jobs.id, { onDelete: 'cascade' }),
    inputHash: text('input_hash').notNull(),
    inputRef: text('input_ref').notNull(),
    position: integer('position').notNull(),
    state: text('state').notNull().default('pending'),
    attemptCount: integer('attempt_count').notNull().default(0),
    cacheKey: text('cache_key'),
    output: text('output_json'),
    error: text('error_json'),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_job_items_job_position').on(table.jobId, table.position),
    index('idx_job_items_job_state_position').on(
      table.jobId,
      table.state,
      table.position,
    ),
  ],
);

export const processingCache = sqliteTable(
  'processing_cache',
  {
    cacheKey: text('cache_key').primaryKey(),
    processorId: text('processor_id').notNull(),
    processorVersion: text('processor_version').notNull(),
    inputHash: text('input_hash').notNull(),
    parametersHash: text('parameters_hash').notNull(),
    modelRevision: text('model_revision'),
    output: text('output_json').notNull(),
    createdAt: text('created_at').notNull(),
    lastAccessedAt: text('last_accessed_at').notNull(),
    hitCount: integer('hit_count').notNull().default(0),
  },
  (table) => [
    index('idx_processing_cache_processor_input').on(
      table.processorId,
      table.processorVersion,
      table.inputHash,
    ),
  ],
);

export const jobEvents = sqliteTable(
  'job_events',
  {
    id: integer('id').primaryKey({ autoIncrement: true }),
    jobId: text('job_id')
      .notNull()
      .references(() => jobs.id, { onDelete: 'cascade' }),
    level: text('level').notNull(),
    eventType: text('event_type').notNull(),
    message: text('message').notNull(),
    details: text('details_json').notNull().default('{}'),
    createdAt: text('created_at').notNull(),
  },
  (table) => [index('idx_job_events_job_id_id').on(table.jobId, table.id)],
);

export const datasetVersions = sqliteTable(
  'dataset_versions',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    version: integer('version').notNull(),
    manifestHash: text('manifest_hash').notNull(),
    sampleCount: integer('sample_count').notNull(),
    splitSeed: integer('split_seed').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_dataset_versions_project').on(
      table.projectId,
      table.version,
    ),
  ],
);

export const providerImports = sqliteTable(
  'provider_imports',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id, { onDelete: 'cascade' }),
    sourceId: text('source_id').references(() => sources.id),
    providerId: text('provider_id').notNull(),
    providerVersion: text('provider_version'),
    datasetId: text('dataset_id').notNull(),
    requestedRevision: text('requested_revision'),
    resolvedRevision: text('resolved_revision'),
    sourceUri: text('source_uri'),
    title: text('title'),
    license: text('license'),
    state: text('state').notNull(),
    allowPatterns: text('allow_patterns_json').notNull().default('[]'),
    ignorePatterns: text('ignore_patterns_json').notNull().default('[]'),
    maxFiles: integer('max_files').notNull(),
    maxFileBytes: integer('max_file_bytes').notNull(),
    maxTotalBytes: integer('max_total_bytes').notNull(),
    fileCount: integer('file_count').notNull().default(0),
    filteredCount: integer('filtered_count').notNull().default(0),
    importedCount: integer('imported_count').notNull().default(0),
    skippedCount: integer('skipped_count').notNull().default(0),
    failedCount: integer('failed_count').notNull().default(0),
    importedBytes: integer('imported_bytes').notNull().default(0),
    manifestHash: text('manifest_hash'),
    error: text('error'),
    metadata: text('metadata_json').notNull().default('{}'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    index('idx_provider_imports_project_created').on(
      table.projectId,
      table.createdAt,
      table.id,
    ),
    index('idx_provider_imports_provider_dataset_revision').on(
      table.providerId,
      table.datasetId,
      table.resolvedRevision,
    ),
  ],
);

export const providerImportFiles = sqliteTable(
  'provider_import_files',
  {
    importId: text('import_id')
      .notNull()
      .references(() => providerImports.id, { onDelete: 'cascade' }),
    relativePath: text('relative_path').notNull(),
    byteSize: integer('byte_size'),
    expectedSha256: text('expected_sha256'),
    etag: text('etag'),
    state: text('state').notNull().default('pending'),
    assetId: text('asset_id').references(() => assets.id),
    actualSha256: text('actual_sha256'),
    objectKey: text('object_key'),
    error: text('error'),
    metadata: text('metadata_json').notNull().default('{}'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.importId, table.relativePath] }),
    index('idx_provider_import_files_import_state').on(
      table.importId,
      table.state,
    ),
  ],
);

export const imageAnalysis = sqliteTable(
  'image_analysis',
  {
    sha256: text('sha256').primaryKey(),
    valid: integer('valid', { mode: 'boolean' }).notNull(),
    format: text('format'),
    mimeType: text('mime_type'),
    width: integer('width'),
    height: integer('height'),
    colorMode: text('color_mode'),
    exifOrientation: integer('exif_orientation'),
    hasAlpha: integer('has_alpha', { mode: 'boolean' })
      .notNull()
      .default(false),
    perceptualHash: text('perceptual_hash'),
    blurScore: real('blur_score'),
    qualityScore: real('quality_score'),
    error: text('error'),
    ocr: text('ocr_json'),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [index('idx_image_analysis_phash').on(table.perceptualHash)],
);

export const derivedImages = sqliteTable(
  'derived_images',
  {
    id: text('id').primaryKey(),
    sourceSha256: text('source_sha256').notNull(),
    sha256: text('sha256').notNull(),
    objectKey: text('object_key').notNull(),
    kind: text('kind').notNull(),
    format: text('format').notNull(),
    width: integer('width').notNull(),
    height: integer('height').notNull(),
    parameters: text('parameters_json').notNull(),
    parametersHash: text('parameters_hash').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_derived_images_source_kind_parameters').on(
      table.sourceSha256,
      table.kind,
      table.parametersHash,
    ),
    index('idx_derived_images_source').on(table.sourceSha256, table.kind),
  ],
);

export const datasetSamples = sqliteTable(
  'dataset_samples',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    assetId: text('asset_id')
      .notNull()
      .references(() => assets.id),
    label: text('label').notNull().default('unlabeled'),
    split: text('split'),
    sourceKey: text('source_key'),
    groupKey: text('group_key'),
    splitSeed: integer('split_seed'),
    splitStrategy: text('split_strategy'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_dataset_samples_project_asset').on(
      table.projectId,
      table.assetId,
    ),
    index('idx_dataset_samples_project_split').on(table.projectId, table.split),
  ],
);

export const duplicateGroups = sqliteTable(
  'duplicate_groups',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    method: text('method').notNull(),
    groupKey: text('group_key').notNull(),
    canonicalAssetId: text('canonical_asset_id').references(() => assets.id),
    maximumDistance: integer('maximum_distance').notNull().default(0),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_duplicate_groups_project_method').on(
      table.projectId,
      table.method,
    ),
  ],
);

export const duplicateGroupMembers = sqliteTable(
  'duplicate_group_members',
  {
    groupId: text('group_id')
      .notNull()
      .references(() => duplicateGroups.id, { onDelete: 'cascade' }),
    assetId: text('asset_id')
      .notNull()
      .references(() => assets.id),
  },
  (table) => [primaryKey({ columns: [table.groupId, table.assetId] })],
);

export const leakageIssues = sqliteTable(
  'leakage_issues',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    leftAssetId: text('left_asset_id')
      .notNull()
      .references(() => assets.id),
    rightAssetId: text('right_asset_id')
      .notNull()
      .references(() => assets.id),
    leftSplit: text('left_split').notNull(),
    rightSplit: text('right_split').notNull(),
    kind: text('kind').notNull(),
    distance: integer('distance').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_leakage_issues_pair_kind').on(
      table.projectId,
      table.leftAssetId,
      table.rightAssetId,
      table.kind,
    ),
    index('idx_leakage_issues_project_kind').on(table.projectId, table.kind),
  ],
);

export const datasetExports = sqliteTable(
  'dataset_exports',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    exporterId: text('exporter_id').notNull(),
    path: text('path').notNull(),
    manifestHash: text('manifest_hash').notNull(),
    sampleCount: integer('sample_count').notNull(),
    splitCounts: text('split_counts_json').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_dataset_exports_project_created').on(
      table.projectId,
      table.createdAt,
    ),
  ],
);

export const tabularAnalysis = sqliteTable(
  'tabular_analysis',
  {
    analysisKey: text('analysis_key').primaryKey(),
    sourceSha256: text('source_sha256').notNull(),
    sourceFormat: text('source_format').notNull(),
    normalizedSha256: text('normalized_sha256').notNull(),
    normalizedObjectKey: text('normalized_object_key').notNull(),
    rowCount: integer('row_count').notNull(),
    columnCount: integer('column_count').notNull(),
    schema: text('schema_json').notNull(),
    profile: text('profile_json').notNull(),
    options: text('options_json').notNull().default('{}'),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    index('idx_tabular_analysis_source').on(
      table.sourceSha256,
      table.sourceFormat,
    ),
  ],
);

export const tabularDatasets = sqliteTable(
  'tabular_datasets',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id),
    assetId: text('asset_id')
      .notNull()
      .references(() => assets.id),
    analysisKey: text('analysis_key').notNull(),
    name: text('name').notNull(),
    schemaMapping: text('schema_mapping_json').notNull().default('{}'),
    customMetadata: text('custom_metadata_json').notNull().default('{}'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_tabular_datasets_project_asset').on(
      table.projectId,
      table.assetId,
    ),
    index('idx_tabular_datasets_project_created').on(
      table.projectId,
      table.createdAt,
    ),
  ],
);

export const tabularQueries = sqliteTable(
  'tabular_queries',
  {
    id: text('id').primaryKey(),
    datasetId: text('dataset_id')
      .notNull()
      .references(() => tabularDatasets.id, { onDelete: 'cascade' }),
    query: text('query_json').notNull(),
    rowCount: integer('row_count').notNull(),
    durationMs: real('duration_ms').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_tabular_queries_dataset_created').on(
      table.datasetId,
      table.createdAt,
    ),
  ],
);

export const tabularExports = sqliteTable(
  'tabular_exports',
  {
    id: text('id').primaryKey(),
    datasetId: text('dataset_id')
      .notNull()
      .references(() => tabularDatasets.id, { onDelete: 'cascade' }),
    format: text('format').notNull(),
    path: text('path').notNull(),
    sha256: text('sha256').notNull(),
    rowCount: integer('row_count').notNull(),
    columnCount: integer('column_count').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_tabular_exports_dataset_created').on(
      table.datasetId,
      table.createdAt,
    ),
  ],
);
export const documentAnalysis = sqliteTable('document_analysis', {
  sourceSha256: text('source_sha256').primaryKey(),
  documentFormat: text('document_format').notNull(),
  valid: integer('valid', { mode: 'boolean' }).notNull(),
  title: text('title'),
  pageCount: integer('page_count'),
  blockCount: integer('block_count').notNull(),
  characterCount: integer('character_count').notNull(),
  parserRevision: text('parser_revision').notNull(),
  error: text('error'),
  updatedAt: text('updated_at').notNull(),
});

export const documentIndexes = sqliteTable(
  'document_indexes',
  {
    assetId: text('asset_id')
      .primaryKey()
      .references(() => assets.id, { onDelete: 'cascade' }),
    sourceSha256: text('source_sha256').notNull(),
    documentFormat: text('document_format').notNull(),
    title: text('title'),
    parserRevision: text('parser_revision').notNull(),
    chunking: text('chunking_json').notNull(),
    modelId: text('model_id').notNull(),
    modelRevision: text('model_revision').notNull(),
    dimensions: integer('dimensions').notNull(),
    chunkCount: integer('chunk_count').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [index('idx_document_indexes_source').on(table.sourceSha256)],
);

export const embeddings = sqliteTable(
  'embeddings',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id, { onDelete: 'cascade' }),
    contentUnitId: text('content_unit_id')
      .notNull()
      .references(() => contentUnits.id, { onDelete: 'cascade' }),
    sourceSha256: text('source_sha256').notNull(),
    modelId: text('model_id').notNull(),
    modelRevision: text('model_revision').notNull(),
    dimensions: integer('dimensions').notNull(),
    vector: blob('vector_blob', { mode: 'buffer' }).notNull(),
    vectorNorm: real('vector_norm').notNull(),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_embeddings_unit_revision').on(
      table.contentUnitId,
      table.modelRevision,
    ),
    index('idx_embeddings_project_model').on(
      table.projectId,
      table.modelId,
      table.modelRevision,
    ),
  ],
);
export const mediaAnalysis = sqliteTable(
  'media_analysis',
  {
    sha256: text('sha256').primaryKey(),
    valid: integer('valid').notNull(),
    mediaKind: text('media_kind').notNull(),
    container: text('container'),
    durationSeconds: real('duration_seconds'),
    bitRate: integer('bit_rate'),
    sizeBytes: integer('size_bytes'),
    videoCodec: text('video_codec'),
    width: integer('width'),
    height: integer('height'),
    fps: real('fps'),
    pixelFormat: text('pixel_format'),
    audioCodec: text('audio_codec'),
    sampleRate: integer('sample_rate'),
    channels: integer('channels'),
    channelLayout: text('channel_layout'),
    tags: text('tags_json').notNull().default('{}'),
    toolRevision: text('tool_revision'),
    error: text('error'),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    index('idx_media_analysis_kind_valid').on(table.mediaKind, table.valid),
  ],
);

export const derivedMedia = sqliteTable(
  'derived_media',
  {
    id: text('id').primaryKey(),
    sourceSha256: text('source_sha256').notNull(),
    sha256: text('sha256').notNull(),
    objectKey: text('object_key').notNull(),
    kind: text('kind').notNull(),
    format: text('format').notNull(),
    mimeType: text('mime_type').notNull(),
    parameters: text('parameters_json').notNull(),
    parametersHash: text('parameters_hash').notNull(),
    durationSeconds: real('duration_seconds'),
    toolRevision: text('tool_revision'),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_derived_media_source_kind_parameters').on(
      table.sourceSha256,
      table.kind,
      table.parametersHash,
    ),
    index('idx_derived_media_source_kind').on(table.sourceSha256, table.kind),
  ],
);
export const acquisitionRequests = sqliteTable(
  'acquisition_requests',
  {
    id: text('id').primaryKey(),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id, { onDelete: 'cascade' }),
    originalPrompt: text('original_prompt'),
    spec: text('spec_json').notNull(),
    plannerId: text('planner_id').notNull(),
    status: text('status').notNull(),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    index('idx_acquisition_requests_project_created').on(
      table.projectId,
      table.createdAt,
      table.id,
    ),
  ],
);

export const acquisitionPlans = sqliteTable(
  'acquisition_plans',
  {
    id: text('id').primaryKey(),
    requestId: text('request_id')
      .notNull()
      .references(() => acquisitionRequests.id, { onDelete: 'cascade' }),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id, { onDelete: 'cascade' }),
    spec: text('spec_json').notNull(),
    queries: text('queries_json').notNull(),
    providers: text('providers_json').notNull(),
    strategy: text('strategy_json').notNull(),
    estimatedMinCandidates: integer('estimated_min_candidates').notNull(),
    estimatedMaxCandidates: integer('estimated_max_candidates').notNull(),
    state: text('state').notNull(),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    index('idx_acquisition_plans_project_created').on(
      table.projectId,
      table.createdAt,
      table.id,
    ),
  ],
);

export const acquisitionRuns = sqliteTable(
  'acquisition_runs',
  {
    id: text('id').primaryKey(),
    planId: text('plan_id')
      .notNull()
      .references(() => acquisitionPlans.id, { onDelete: 'cascade' }),
    projectId: text('project_id')
      .notNull()
      .references(() => projects.id, { onDelete: 'cascade' }),
    jobId: text('job_id'),
    state: text('state').notNull(),
    dryRun: integer('dry_run').notNull().default(0),
    targetCount: integer('target_count').notNull(),
    maxCandidates: integer('max_candidates').notNull(),
    maxDownloadBytes: integer('max_download_bytes').notNull(),
    downloadedCount: integer('downloaded_count').notNull().default(0),
    bytesDownloaded: integer('bytes_downloaded').notNull().default(0),
    requestCount: integer('request_count').notNull().default(0),
    cycleCount: integer('cycle_count').notNull().default(0),
    observedYield: real('observed_yield').notNull().default(0),
    nextBatchSize: integer('next_batch_size').notNull().default(0),
    stopReason: text('stop_reason'),
    error: text('error'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
    completedAt: text('completed_at'),
  },
  (table) => [
    index('idx_acquisition_runs_project_created').on(
      table.projectId,
      table.createdAt,
      table.id,
    ),
    index('idx_acquisition_runs_state_updated').on(
      table.state,
      table.updatedAt,
    ),
  ],
);

export const acquisitionQueries = sqliteTable(
  'acquisition_queries',
  {
    id: text('id').primaryKey(),
    runId: text('run_id')
      .notNull()
      .references(() => acquisitionRuns.id, { onDelete: 'cascade' }),
    providerId: text('provider_id').notNull(),
    query: text('query').notNull(),
    origin: text('origin').notNull(),
    priority: real('priority').notNull().default(1),
    cursor: text('cursor'),
    resultCount: integer('result_count').notNull().default(0),
    evaluatedCount: integer('evaluated_count').notNull().default(0),
    acceptedCount: integer('accepted_count').notNull().default(0),
    errorCount: integer('error_count').notNull().default(0),
    exhausted: integer('exhausted').notNull().default(0),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_acquisition_queries_run_provider_query').on(
      table.runId,
      table.providerId,
      table.query,
    ),
    index('idx_acquisition_queries_run_priority').on(
      table.runId,
      table.exhausted,
      table.priority,
      table.createdAt,
    ),
  ],
);

export const acquisitionCandidates = sqliteTable(
  'acquisition_candidates',
  {
    id: text('id').primaryKey(),
    runId: text('run_id')
      .notNull()
      .references(() => acquisitionRuns.id, { onDelete: 'cascade' }),
    queryId: text('query_id').references(() => acquisitionQueries.id, {
      onDelete: 'set null',
    }),
    providerId: text('provider_id').notNull(),
    remoteId: text('remote_id').notNull(),
    sourceUrl: text('source_url').notNull(),
    canonicalUrl: text('canonical_url').notNull(),
    landingPageUrl: text('landing_page_url'),
    previewUrl: text('preview_url'),
    title: text('title'),
    description: text('description'),
    mimeType: text('mime_type'),
    declaredWidth: integer('declared_width'),
    declaredHeight: integer('declared_height'),
    author: text('author'),
    license: text('license'),
    estimatedSize: integer('estimated_size'),
    state: text('state').notNull(),
    downloadAttempts: integer('download_attempts').notNull().default(0),
    downloadedBytes: integer('downloaded_bytes').notNull().default(0),
    contentSha256: text('content_sha256'),
    assetId: text('asset_id').references(() => assets.id),
    metadata: text('metadata_json').notNull().default('{}'),
    error: text('error'),
    createdAt: text('created_at').notNull(),
    updatedAt: text('updated_at').notNull(),
  },
  (table) => [
    uniqueIndex('idx_acquisition_candidates_run_provider_remote').on(
      table.runId,
      table.providerId,
      table.remoteId,
    ),
    uniqueIndex('idx_acquisition_candidates_run_url').on(
      table.runId,
      table.canonicalUrl,
    ),
    index('idx_acquisition_candidates_run_state_created').on(
      table.runId,
      table.state,
      table.createdAt,
      table.id,
    ),
  ],
);

export const acquisitionDecisions = sqliteTable(
  'acquisition_decisions',
  {
    id: text('id').primaryKey(),
    runId: text('run_id')
      .notNull()
      .references(() => acquisitionRuns.id, { onDelete: 'cascade' }),
    candidateId: text('candidate_id')
      .notNull()
      .references(() => acquisitionCandidates.id, { onDelete: 'cascade' }),
    decision: text('decision').notNull(),
    reason: text('reason').notNull(),
    evaluatorId: text('evaluator_id').notNull(),
    evaluatorVersion: text('evaluator_version').notNull(),
    scores: text('scores_json').notNull().default('{}'),
    human: integer('human').notNull().default(0),
    createdAt: text('created_at').notNull(),
  },
  (table) => [
    index('idx_acquisition_decisions_run_reason').on(
      table.runId,
      table.reason,
      table.createdAt,
    ),
  ],
);
export const workspaceState = sqliteTable('workspace_state', {
  id: text('id').primaryKey(),
  state: text('state_json').notNull(),
  updatedAt: text('updated_at').notNull(),
});
