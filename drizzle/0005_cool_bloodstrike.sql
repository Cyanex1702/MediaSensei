CREATE TABLE `document_analysis` (
	`source_sha256` text PRIMARY KEY NOT NULL,
	`document_format` text NOT NULL,
	`valid` integer NOT NULL,
	`title` text,
	`page_count` integer,
	`block_count` integer NOT NULL,
	`character_count` integer NOT NULL,
	`parser_revision` text NOT NULL,
	`error` text,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `document_indexes` (
	`asset_id` text PRIMARY KEY NOT NULL,
	`source_sha256` text NOT NULL,
	`document_format` text NOT NULL,
	`title` text,
	`parser_revision` text NOT NULL,
	`chunking_json` text NOT NULL,
	`model_id` text NOT NULL,
	`model_revision` text NOT NULL,
	`dimensions` integer NOT NULL,
	`chunk_count` integer NOT NULL,
	`updated_at` text NOT NULL,
	FOREIGN KEY (`asset_id`) REFERENCES `assets`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_document_indexes_source` ON `document_indexes` (`source_sha256`);--> statement-breakpoint
CREATE TABLE `embeddings` (
	`id` text PRIMARY KEY NOT NULL,
	`project_id` text NOT NULL,
	`content_unit_id` text NOT NULL,
	`source_sha256` text NOT NULL,
	`model_id` text NOT NULL,
	`model_revision` text NOT NULL,
	`dimensions` integer NOT NULL,
	`vector_blob` blob NOT NULL,
	`vector_norm` real NOT NULL,
	`created_at` text NOT NULL,
	FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`content_unit_id`) REFERENCES `content_units`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_embeddings_unit_revision` ON `embeddings` (`content_unit_id`,`model_revision`);--> statement-breakpoint
CREATE INDEX `idx_embeddings_project_model` ON `embeddings` (`project_id`,`model_id`,`model_revision`);--> statement-breakpoint
CREATE INDEX `idx_content_units_asset_kind` ON `content_units` (`asset_id`,`kind`);