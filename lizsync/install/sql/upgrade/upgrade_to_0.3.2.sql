BEGIN;

-- conflicts
CREATE TABLE lizsync.conflicts (
    id bigint NOT NULL,
    conflict_time timestamp with time zone DEFAULT now() NOT NULL,
    object_table text,
    object_uid uuid,
    clone_id uuid,
    central_event_id bigint,
    central_event_timestamp timestamp with time zone,
    central_sql text,
    clone_sql text,
    rejected text,
    rule_applied text
);

-- conflicts
COMMENT ON TABLE lizsync.conflicts IS 'Store conflicts resolution made during bidirectionnal database synchronizations.';

-- conflicts_id_seq
CREATE SEQUENCE lizsync.conflicts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- conflicts_id_seq
ALTER SEQUENCE lizsync.conflicts_id_seq OWNED BY lizsync.conflicts.id;

-- conflicts id
ALTER TABLE ONLY lizsync.conflicts ALTER COLUMN id SET DEFAULT nextval('lizsync.conflicts_id_seq'::regclass);

-- conflicts conflicts_pkey
ALTER TABLE ONLY lizsync.conflicts
    ADD CONSTRAINT conflicts_pkey PRIMARY KEY (id);

-- conflicts
COMMENT ON TABLE lizsync.conflicts IS 'Store conflicts resolution made during bidirectionnal database synchronizations.';

-- conflicts.id
COMMENT ON COLUMN lizsync.conflicts.id IS 'Automatic ID';

-- conflicts.conflict_time
COMMENT ON COLUMN lizsync.conflicts.conflict_time IS 'Timestamp of the conflict resolution. Not related to timestamp of logged actions';

-- conflicts.object_table
COMMENT ON COLUMN lizsync.conflicts.object_table IS 'Schema and table name of the conflicted object.';

-- conflicts.object_uid
COMMENT ON COLUMN lizsync.conflicts.object_uid IS 'UID of the conflicted object.';

-- conflicts.clone_id
COMMENT ON COLUMN lizsync.conflicts.clone_id IS 'UID of the source clone database.';

-- conflicts.central_event_id
COMMENT ON COLUMN lizsync.conflicts.central_event_id IS 'Event id of the conflicted central audit log';

-- conflicts.central_event_timestamp
COMMENT ON COLUMN lizsync.conflicts.central_event_timestamp IS 'Event action_tstamp_tx of the conflicted central audit log';

-- conflicts.central_sql
COMMENT ON COLUMN lizsync.conflicts.central_sql IS 'Central SQL action in conflict';

-- conflicts.clone_sql
COMMENT ON COLUMN lizsync.conflicts.clone_sql IS 'Clone SQL action in conflict';

-- conflicts.rejected
COMMENT ON COLUMN lizsync.conflicts.rejected IS 'Rejected object. If "clone", it means the central data has been kept instead';

-- conflicts.rule_applied
COMMENT ON COLUMN lizsync.conflicts.rule_applied IS 'Rule used when managing conflict';

COMMIT;
