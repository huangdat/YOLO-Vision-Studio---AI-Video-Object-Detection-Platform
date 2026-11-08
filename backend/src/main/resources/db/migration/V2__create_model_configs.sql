CREATE TABLE model_configs (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    model_key VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL,
    model_size VARCHAR(16) NOT NULL,
    task_type VARCHAR(32) NOT NULL,
    weights_filename VARCHAR(255) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_model_configs PRIMARY KEY (id),
    CONSTRAINT uk_model_configs_model_key UNIQUE (model_key)
);
