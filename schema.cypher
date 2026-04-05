-- ============================================================
-- Second Brain — ArcadeDB Schema
-- Run these via execute_command through the MCP server
-- or paste into ArcadeDB Studio console
-- ============================================================

-- ============================================================
-- VERTEX TYPES
-- ============================================================

-- Concept: atomic unit of knowledge
-- Ideas, terms, techniques, principles, technologies
CREATE VERTEX TYPE Concept IF NOT EXISTS;
CREATE PROPERTY Concept.name IF NOT EXISTS STRING;
CREATE PROPERTY Concept.description IF NOT EXISTS STRING;
CREATE PROPERTY Concept.embedding IF NOT EXISTS LIST;
CREATE PROPERTY Concept.created_at IF NOT EXISTS DATETIME;
CREATE PROPERTY Concept.updated_at IF NOT EXISTS DATETIME;
CREATE PROPERTY Concept.source IF NOT EXISTS STRING;
CREATE PROPERTY Concept.aliases IF NOT EXISTS LIST;
CREATE PROPERTY Concept.metadata IF NOT EXISTS MAP;
CREATE INDEX ON Concept(name) UNIQUE;

-- Artifact: concrete thing that was produced or consumed
-- Conversation transcripts, files, code commits, documents, places
-- Immutable snapshots — don't update, create new ones
CREATE VERTEX TYPE Artifact IF NOT EXISTS;
CREATE PROPERTY Artifact.name IF NOT EXISTS STRING;
CREATE PROPERTY Artifact.source_type IF NOT EXISTS STRING;
CREATE PROPERTY Artifact.source_path IF NOT EXISTS STRING;
CREATE PROPERTY Artifact.content_hash IF NOT EXISTS STRING;
CREATE PROPERTY Artifact.summary IF NOT EXISTS STRING;
CREATE PROPERTY Artifact.embedding IF NOT EXISTS LIST;
CREATE PROPERTY Artifact.created_at IF NOT EXISTS DATETIME;
CREATE PROPERTY Artifact.source_timestamp IF NOT EXISTS DATETIME;
CREATE PROPERTY Artifact.metadata IF NOT EXISTS MAP;
CREATE INDEX ON Artifact(content_hash) UNIQUE;
CREATE INDEX ON Artifact(source_type) NOTUNIQUE;

-- Decision: a choice that was made with reasoning
-- Highest value node type — captures why, not just what
CREATE VERTEX TYPE Decision IF NOT EXISTS;
CREATE PROPERTY Decision.name IF NOT EXISTS STRING;
CREATE PROPERTY Decision.what IF NOT EXISTS STRING;
CREATE PROPERTY Decision.alternatives IF NOT EXISTS LIST;
CREATE PROPERTY Decision.reasoning IF NOT EXISTS STRING;
CREATE PROPERTY Decision.confidence IF NOT EXISTS STRING;
CREATE PROPERTY Decision.still_valid IF NOT EXISTS BOOLEAN;
CREATE PROPERTY Decision.embedding IF NOT EXISTS LIST;
CREATE PROPERTY Decision.created_at IF NOT EXISTS DATETIME;
CREATE PROPERTY Decision.reviewed_at IF NOT EXISTS DATETIME;
CREATE PROPERTY Decision.metadata IF NOT EXISTS MAP;

-- Person: anyone referenced across your knowledge
CREATE VERTEX TYPE Person IF NOT EXISTS;
CREATE PROPERTY Person.name IF NOT EXISTS STRING;
CREATE PROPERTY Person.context IF NOT EXISTS STRING;
CREATE PROPERTY Person.relationship IF NOT EXISTS STRING;
CREATE PROPERTY Person.metadata IF NOT EXISTS MAP;
CREATE PROPERTY Person.created_at IF NOT EXISTS DATETIME;
CREATE INDEX ON Person(name) UNIQUE;

-- Project: a grouping context — gravitational well
CREATE VERTEX TYPE Project IF NOT EXISTS;
CREATE PROPERTY Project.name IF NOT EXISTS STRING;
CREATE PROPERTY Project.description IF NOT EXISTS STRING;
CREATE PROPERTY Project.status IF NOT EXISTS STRING;
CREATE PROPERTY Project.started_at IF NOT EXISTS DATETIME;
CREATE PROPERTY Project.metadata IF NOT EXISTS MAP;
CREATE PROPERTY Project.created_at IF NOT EXISTS DATETIME;
CREATE INDEX ON Project(name) UNIQUE;


-- ============================================================
-- EDGE TYPES
-- ============================================================

-- General semantic link between Concepts
-- label: "implements", "replaces", "contradicts", "extends", "depends_on", "is_aspect_of"
CREATE EDGE TYPE RELATES_TO IF NOT EXISTS;
CREATE PROPERTY RELATES_TO.label IF NOT EXISTS STRING;
CREATE PROPERTY RELATES_TO.weight IF NOT EXISTS DOUBLE;
CREATE PROPERTY RELATES_TO.created_at IF NOT EXISTS DATETIME;

-- From Artifact to Concept, Person, Decision, or Project
-- Tracks what an artifact references
CREATE EDGE TYPE MENTIONS IF NOT EXISTS;
CREATE PROPERTY MENTIONS.context IF NOT EXISTS STRING;
CREATE PROPERTY MENTIONS.created_at IF NOT EXISTS DATETIME;

-- Causal chain — from Decision/Concept to another
-- "Choosing X LED_TO simplifying Y"
CREATE EDGE TYPE LED_TO IF NOT EXISTS;
CREATE PROPERTY LED_TO.description IF NOT EXISTS STRING;
CREATE PROPERTY LED_TO.created_at IF NOT EXISTS DATETIME;

-- Contextual grouping — anything to Project
CREATE EDGE TYPE PART_OF IF NOT EXISTS;
CREATE PROPERTY PART_OF.role IF NOT EXISTS STRING;
CREATE PROPERTY PART_OF.created_at IF NOT EXISTS DATETIME;

-- Provenance tracking — where did this come from
-- "This summary was DERIVED_FROM that conversation"
CREATE EDGE TYPE DERIVED_FROM IF NOT EXISTS;
CREATE PROPERTY DERIVED_FROM.method IF NOT EXISTS STRING;
CREATE PROPERTY DERIVED_FROM.created_at IF NOT EXISTS DATETIME;

-- Cross-source conflict tracking
-- When two artifacts make contradictory claims
CREATE EDGE TYPE CONTRADICTS IF NOT EXISTS;
CREATE PROPERTY CONTRADICTS.description IF NOT EXISTS STRING;
CREATE PROPERTY CONTRADICTS.created_at IF NOT EXISTS DATETIME;


-- ============================================================
-- FULL-TEXT INDEXES (for natural language search)
-- ============================================================

-- NOTE: Must use single-field indexes with ENGINE LUCENE.
-- Multi-field FULL_TEXT indexes do not backfill existing data in ArcadeDB v26.4.1.
CREATE INDEX ON Concept(name) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Concept(description) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Artifact(name) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Artifact(summary) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Decision(name) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Decision(what) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Decision(reasoning) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Project(name) FULL_TEXT ENGINE LUCENE;
CREATE INDEX ON Project(description) FULL_TEXT ENGINE LUCENE;
