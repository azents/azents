"""Create the consolidated current-schema baseline.

Revision ID: 6b53a0a15d11
Revises:
Create Date: 2026-09-10 07:39:46.615430

"""

# ruff: noqa: E501

from collections.abc import Sequence

from alembic import op

revision: str = "6b53a0a15d11"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASELINE_SQL = r"""
--
-- PostgreSQL database dump
--


-- Dumped from database version 17.11 (Debian 17.11-1.pgdg13+2)
-- Dumped by pg_dump version 17.11 (Debian 17.11-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: action_execution_event_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.action_execution_event_kind AS ENUM (
    'info',
    'step_started',
    'command_started',
    'stdout',
    'stderr',
    'command_completed',
    'warning',
    'failed',
    'retry_requested',
    'failed_finalized',
    'completed'
);


--
-- Name: action_execution_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.action_execution_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'cancelled'
);


--
-- Name: agent_decommission_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_decommission_status AS ENUM (
    'pending',
    'retiring_sessions',
    'waiting_retention',
    'finalizing',
    'retry_wait',
    'completed'
);


--
-- Name: agent_lifecycle_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_lifecycle_status AS ENUM (
    'active',
    'decommissioning'
);


--
-- Name: agent_project_catalog_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_project_catalog_status AS ENUM (
    'unchecked',
    'available',
    'missing',
    'unavailable',
    'error'
);


--
-- Name: agent_project_default_item_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_project_default_item_type AS ENUM (
    'existing_project',
    'git_worktree'
);


--
-- Name: agent_run_parent_result_delivery_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_run_parent_result_delivery_state AS ENUM (
    'suppressed',
    'enqueued'
);


--
-- Name: agent_run_phase; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_run_phase AS ENUM (
    'idle',
    'preparing_input',
    'waiting_for_model',
    'streaming_model',
    'normalizing_output',
    'executing_tools',
    'appending_events',
    'compacting',
    'stopping'
);


--
-- Name: agent_run_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_run_status AS ENUM (
    'running',
    'completed',
    'stopped',
    'failed',
    'interrupted',
    'cancelled',
    'pending'
);


--
-- Name: agent_runtime_capability; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_runtime_capability AS ENUM (
    'none',
    'managed',
    'removing'
);


--
-- Name: agent_runtime_removal_stage; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_runtime_removal_stage AS ENUM (
    'fencing',
    'interrupting_work',
    'cleaning_product_state',
    'deleting_runtime',
    'finalizing',
    'completed'
);


--
-- Name: agent_runtime_removal_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_runtime_removal_status AS ENUM (
    'pending',
    'running',
    'retry_wait',
    'completed'
);


--
-- Name: agent_session_end_reason; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_end_reason AS ENUM (
    'manual_new',
    'manual_reset',
    'idle',
    'safety',
    'compact_rotate',
    'deleted'
);


--
-- Name: agent_session_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_kind AS ENUM (
    'root',
    'subagent'
);


--
-- Name: agent_session_primary_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_primary_kind AS ENUM (
    'team_primary'
);


--
-- Name: agent_session_product_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_product_mode AS ENUM (
    'team',
    'user'
);


--
-- Name: agent_session_run_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_run_state AS ENUM (
    'idle',
    'running'
);


--
-- Name: agent_session_start_reason; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_start_reason AS ENUM (
    'initial',
    'manual_new',
    'manual_reset',
    'system_recovery',
    'compact_rotate',
    'external_channel'
);


--
-- Name: agent_session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_status AS ENUM (
    'active',
    'archived'
);


--
-- Name: agent_session_title_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_session_title_source AS ENUM (
    'manual',
    'auto_initial',
    'auto_generated'
);


--
-- Name: agent_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_type AS ENUM (
    'public',
    'private'
);


--
-- Name: archived_session_purge_participant_phase; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.archived_session_purge_participant_phase AS ENUM (
    'pending',
    'prepared',
    'cleanup_completed',
    'verified'
);


--
-- Name: archived_session_purge_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.archived_session_purge_status AS ENUM (
    'pending',
    'fencing',
    'cleaning',
    'retry_wait',
    'completed',
    'cancelled'
);


--
-- Name: archived_session_retention_application_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.archived_session_retention_application_status AS ENUM (
    'pending',
    'running',
    'retry_wait',
    'completed'
);


--
-- Name: artifact_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.artifact_status AS ENUM (
    'available',
    'expired'
);


--
-- Name: chat_write_request_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.chat_write_request_type AS ENUM (
    'edit_message',
    'command',
    'failed_run_retry',
    'message',
    'turn_action',
    'model_profile'
);


--
-- Name: chatgpt_oauth_connection_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.chatgpt_oauth_connection_method AS ENUM (
    'callback',
    'device'
);


--
-- Name: chatgpt_oauth_session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.chatgpt_oauth_session_status AS ENUM (
    'pending',
    'connected',
    'cancelled',
    'expired',
    'failed'
);


--
-- Name: event_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.event_kind AS ENUM (
    'user_message',
    'goal_continuation',
    'goal_updated',
    'action_message',
    'agent_message',
    'action_execution_result',
    'skill_loaded',
    'goal_briefing',
    'assistant_message',
    'reasoning',
    'client_tool_call',
    'client_tool_result',
    'provider_tool_call',
    'turn_marker',
    'run_marker',
    'interrupted',
    'compaction_marker',
    'compaction_summary',
    'system_reminder',
    'system_error',
    'unknown_adapter_output',
    'external_channel_message',
    'external_channel_continuation',
    'scheduled_task_trigger',
    'scheduled_task_continuation',
    'scheduled_task_result'
);


--
-- Name: exchange_file_origin; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.exchange_file_origin AS ENUM (
    'upload',
    'artifact'
);


--
-- Name: exchange_file_provenance_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.exchange_file_provenance_kind AS ENUM (
    'human',
    'agent',
    'tool',
    'provider',
    'system',
    'preview',
    'migration'
);


--
-- Name: exchange_file_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.exchange_file_status AS ENUM (
    'available',
    'expired'
);


--
-- Name: external_channel_access_grant_scope; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_access_grant_scope AS ENUM (
    'session',
    'agent'
);


--
-- Name: external_channel_access_request_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_access_request_status AS ENUM (
    'pending',
    'allowed',
    'denied',
    'blocked',
    'expired'
);


--
-- Name: external_channel_app_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_app_mode AS ENUM (
    'single',
    'multi'
);


--
-- Name: external_channel_channel_default_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_channel_default_status AS ENUM (
    'active',
    'invalidated'
);


--
-- Name: external_channel_connection_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_connection_status AS ENUM (
    'configuring',
    'active',
    'degraded',
    'reconnect_required',
    'disconnecting',
    'disconnected'
);


--
-- Name: external_channel_conversation_location; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_conversation_location AS ENUM (
    'channel',
    'threads'
);


--
-- Name: external_channel_conversation_scope_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_conversation_scope_kind AS ENUM (
    'parent_channel',
    'thread'
);


--
-- Name: external_channel_ingress_authority_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_ingress_authority_kind AS ENUM (
    'configuration',
    'lease',
    'durable_replay'
);


--
-- Name: external_channel_ingress_item_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_ingress_item_state AS ENUM (
    'pending',
    'processing',
    'retry_waiting'
);


--
-- Name: external_channel_ingress_profile; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_ingress_profile AS ENUM (
    'slack_http',
    'slack_socket',
    'discord_gateway_http'
);


--
-- Name: external_channel_interaction_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_interaction_status AS ENUM (
    'accepted',
    'processing',
    'completed',
    'expired',
    'rejected',
    'failed'
);


--
-- Name: external_channel_interaction_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_interaction_type AS ENUM (
    'shortcut',
    'block_action',
    'options',
    'view_submission',
    'management_action'
);


--
-- Name: external_channel_participation_setting_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_participation_setting_status AS ENUM (
    'active',
    'invalidated'
);


--
-- Name: external_channel_principal_author_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_principal_author_type AS ENUM (
    'human',
    'bot',
    'app',
    'system'
);


--
-- Name: external_channel_provider; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_provider AS ENUM (
    'slack',
    'discord'
);


--
-- Name: external_channel_resource_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_resource_status AS ENUM (
    'active',
    'unavailable',
    'deleted'
);


--
-- Name: external_channel_resource_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_resource_type AS ENUM (
    'parent_channel',
    'thread'
);


--
-- Name: external_channel_response_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_response_mode AS ENUM (
    'mention_only',
    'all_messages'
);


--
-- Name: external_channel_route_catalog_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_route_catalog_status AS ENUM (
    'available',
    'removed'
);


--
-- Name: external_channel_route_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_route_mode AS ENUM (
    'dedicated',
    'platform'
);


--
-- Name: external_channel_setup_claim_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_setup_claim_status AS ENUM (
    'pending_agent',
    'pending_location',
    'selected',
    'completed',
    'expired',
    'invalidated'
);


--
-- Name: external_channel_transport; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_transport AS ENUM (
    'http',
    'socket'
);


--
-- Name: external_channel_work_projection_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.external_channel_work_projection_status AS ENUM (
    'present',
    'failed',
    'unknown',
    'deleted'
);


--
-- Name: git_worktree_path_claim_owner_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.git_worktree_path_claim_owner_kind AS ENUM (
    'manual_action',
    'archive_cleanup',
    'agent_action'
);


--
-- Name: git_worktree_path_claim_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.git_worktree_path_claim_state AS ENUM (
    'claimed',
    'removing',
    'removed',
    'already_absent',
    'failed',
    'unresolved'
);


--
-- Name: inference_profile_failure_code; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.inference_profile_failure_code AS ENUM (
    'model_target_not_found',
    'model_target_resolution_failed',
    'reasoning_effort_unsupported'
);


--
-- Name: inference_profile_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.inference_profile_source AS ENUM (
    'explicit_input',
    'session_last_used',
    'agent_default',
    'parent_run',
    'retry_original',
    'spawn_override'
);


--
-- Name: invitation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.invitation_status AS ENUM (
    'pending',
    'accepted',
    'declined'
);


--
-- Name: join_request_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.join_request_status AS ENUM (
    'pending',
    'muted'
);


--
-- Name: kimi_oauth_connection_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.kimi_oauth_connection_method AS ENUM (
    'device'
);


--
-- Name: kimi_oauth_session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.kimi_oauth_session_status AS ENUM (
    'pending',
    'connected',
    'cancelled',
    'expired',
    'failed'
);


--
-- Name: llm_catalog_attempt_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.llm_catalog_attempt_status AS ENUM (
    'running',
    'succeeded',
    'failed'
);


--
-- Name: llm_catalog_entry_visibility; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.llm_catalog_entry_visibility AS ENUM (
    'selectable',
    'hidden'
);


--
-- Name: llm_catalog_lowerer_target; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.llm_catalog_lowerer_target AS ENUM (
    'litellm'
);


--
-- Name: llm_catalog_scope; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.llm_catalog_scope AS ENUM (
    'system',
    'integration'
);


--
-- Name: llm_model_lifecycle_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.llm_model_lifecycle_status AS ENUM (
    'active',
    'deprecated',
    'removed_from_source',
    'local_only',
    'disabled'
);


--
-- Name: llm_provider; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.llm_provider AS ENUM (
    'openai',
    'anthropic',
    'google_gemini',
    'aws_bedrock',
    'google_vertex_ai',
    'chatgpt_oauth',
    'xai_oauth',
    'xai',
    'openrouter',
    'kimi_oauth'
);


--
-- Name: mailbox_item_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.mailbox_item_kind AS ENUM (
    'user_message',
    'goal_continuation',
    'action_message',
    'agent_message',
    'external_channel_message',
    'external_channel_continuation',
    'turn_action_continuation',
    'scheduled_task_trigger',
    'scheduled_task_continuation'
);


--
-- Name: mailbox_item_scheduling_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.mailbox_item_scheduling_mode AS ENUM (
    'queue_only',
    'wake_session'
);


--
-- Name: mcp_oauth_connection_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.mcp_oauth_connection_status AS ENUM (
    'connected',
    'reconnect_required'
);


--
-- Name: memory_scope; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.memory_scope AS ENUM (
    'agent',
    'user'
);


--
-- Name: model_file_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.model_file_status AS ENUM (
    'available',
    'deleted'
);


--
-- Name: model_reasoning_effort; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.model_reasoning_effort AS ENUM (
    'none',
    'minimal',
    'low',
    'medium',
    'high',
    'xhigh',
    'max'
);


--
-- Name: owner_lifecycle_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.owner_lifecycle_kind AS ENUM (
    'membership_archive',
    'account_purge'
);


--
-- Name: owner_lifecycle_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.owner_lifecycle_status AS ENUM (
    'pending',
    'retiring_sessions',
    'waiting_purge',
    'finalizing',
    'retry_wait',
    'completed'
);


--
-- Name: runtime_configuration_state_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_configuration_state_status AS ENUM (
    'unconfigured',
    'blocked',
    'ready'
);


--
-- Name: runtime_connection_authority_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_connection_authority_kind AS ENUM (
    'provider',
    'runner'
);


--
-- Name: runtime_desired_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_desired_state AS ENUM (
    'running',
    'stopped'
);


--
-- Name: runtime_infrastructure_profile_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_infrastructure_profile_kind AS ENUM (
    'kubernetes_pod',
    'docker_container'
);


--
-- Name: runtime_lifecycle_command_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_lifecycle_command_type AS ENUM (
    'start',
    'stop',
    'restart',
    'reset',
    'observe'
);


--
-- Name: runtime_profile_lifecycle; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_profile_lifecycle AS ENUM (
    'active',
    'disabled'
);


--
-- Name: runtime_provider_audit_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_audit_event_type AS ENUM (
    'registered',
    'bootstrap_reconciled',
    'bootstrap_withdrawn',
    'bootstrap_conflict',
    'enabled',
    'disabled',
    'availability_changed',
    'enrollment_grant_issued',
    'credential_issued',
    'credential_revoked',
    'connection_opened',
    'connection_closed'
);


--
-- Name: runtime_provider_auth_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_auth_method AS ENUM (
    'azents_issued_token',
    'kubernetes_service_account'
);


--
-- Name: runtime_provider_availability_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_availability_mode AS ENUM (
    'platform_wide',
    'selected_workspaces'
);


--
-- Name: runtime_provider_binding_audit_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_binding_audit_event_type AS ENUM (
    'created',
    'reconciled',
    'authenticated',
    'connected',
    'rotated',
    'revoked',
    'conflict'
);


--
-- Name: runtime_provider_binding_origin; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_binding_origin AS ENUM (
    'agent_explicit',
    'platform_default',
    'migration'
);


--
-- Name: runtime_provider_binding_owner; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_binding_owner AS ENUM (
    'admin',
    'bootstrap'
);


--
-- Name: runtime_provider_binding_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_binding_state AS ENUM (
    'active',
    'revoked'
);


--
-- Name: runtime_provider_bootstrap_adapter_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_bootstrap_adapter_kind AS ENUM (
    'helm_file'
);


--
-- Name: runtime_provider_bootstrap_declaration_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_bootstrap_declaration_state AS ENUM (
    'present',
    'absent',
    'conflict'
);


--
-- Name: runtime_provider_config_revision_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_config_revision_state AS ENUM (
    'candidate',
    'provider_accepted',
    'active',
    'superseded',
    'rejected',
    'divergent'
);


--
-- Name: runtime_provider_config_validation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_config_validation_status AS ENUM (
    'pending',
    'valid',
    'invalid'
);


--
-- Name: runtime_provider_connection_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_connection_state AS ENUM (
    'connected',
    'disconnected'
);


--
-- Name: runtime_provider_connection_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_connection_status AS ENUM (
    'connected',
    'disconnected'
);


--
-- Name: runtime_provider_credential_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_credential_state AS ENUM (
    'active',
    'revoked'
);


--
-- Name: runtime_provider_enrollment_grant_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_enrollment_grant_state AS ENUM (
    'issued',
    'consumed',
    'revoked'
);


--
-- Name: runtime_provider_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_kind AS ENUM (
    'kubernetes',
    'docker'
);


--
-- Name: runtime_provider_lifecycle_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_lifecycle_state AS ENUM (
    'active',
    'decommissioning',
    'decommissioned',
    'force_retired'
);


--
-- Name: runtime_provider_observed_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_observed_state AS ENUM (
    'unknown',
    'stopped',
    'starting',
    'running',
    'stopping',
    'recovering',
    'resetting',
    'failed'
);


--
-- Name: runtime_provider_registration_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_registration_method AS ENUM (
    'admin',
    'bootstrap'
);


--
-- Name: runtime_provider_scope; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_provider_scope AS ENUM (
    'system',
    'workspace'
);


--
-- Name: runtime_reconcile_source_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_reconcile_source_kind AS ENUM (
    'provider_capability',
    'provider',
    'infrastructure_profile',
    'workspace_runtime_profile',
    'agent_selection'
);


--
-- Name: runtime_reconcile_task_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_reconcile_task_status AS ENUM (
    'pending',
    'running',
    'retry_wait',
    'completed'
);


--
-- Name: runtime_recreation_item_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_recreation_item_status AS ENUM (
    'pending',
    'running',
    'succeeded',
    'skipped',
    'failed'
);


--
-- Name: runtime_recreation_operation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_recreation_operation_status AS ENUM (
    'pending',
    'running',
    'completed',
    'completed_with_failures',
    'failed'
);


--
-- Name: runtime_recreation_target_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_recreation_target_kind AS ENUM (
    'provider',
    'infrastructure_profile',
    'workspace_runtime_profile'
);


--
-- Name: runtime_runner_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_runner_state AS ENUM (
    'unknown',
    'disconnected',
    'starting',
    'ready',
    'degraded',
    'failed'
);


--
-- Name: runtime_terminal_delete_acknowledgement_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.runtime_terminal_delete_acknowledgement_kind AS ENUM (
    'provider_report',
    'no_physical_binding'
);


--
-- Name: sandbox_checkpoint_format; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sandbox_checkpoint_format AS ENUM (
    'tar_zst'
);


--
-- Name: sandbox_checkpoint_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sandbox_checkpoint_kind AS ENUM (
    'hibernate',
    'debounce',
    'manual'
);


--
-- Name: sandbox_runtime_lease_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sandbox_runtime_lease_state AS ENUM (
    'allocating',
    'starting',
    'running',
    'hibernating',
    'hibernated',
    'deleting',
    'lost'
);


--
-- Name: schedule_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.schedule_type AS ENUM (
    'cron',
    'once'
);


--
-- Name: scheduled_task_schedule_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scheduled_task_schedule_type AS ENUM (
    'once',
    'cron'
);


--
-- Name: scheduled_task_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scheduled_task_status AS ENUM (
    'idle',
    'running',
    'succeeded',
    'failed'
);


--
-- Name: session_agent_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_agent_kind AS ENUM (
    'root',
    'subagent'
);


--
-- Name: session_git_worktree_branch_created_by; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_git_worktree_branch_created_by AS ENUM (
    'azents'
);


--
-- Name: session_git_worktree_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_git_worktree_status AS ENUM (
    'pending',
    'creating',
    'ready',
    'failed',
    'cleanup_pending',
    'cleaned',
    'cleanup_failed'
);


--
-- Name: session_working_folder_binding_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_working_folder_binding_state AS ENUM (
    'none',
    'pending',
    'bound',
    'invalidated'
);


--
-- Name: session_working_folder_cleanup_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_working_folder_cleanup_status AS ENUM (
    'not_attempted',
    'pending',
    'succeeded',
    'failed'
);


--
-- Name: signup_token_delivery_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.signup_token_delivery_method AS ENUM (
    'manual',
    'email'
);


--
-- Name: snapshot_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.snapshot_kind AS ENUM (
    'hibernate',
    'debounce'
);


--
-- Name: system_data_migration_outcome; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_data_migration_outcome AS ENUM (
    'applied',
    'skipped'
);


--
-- Name: system_setting_audit_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_setting_audit_event_type AS ENUM (
    'candidate_replaced',
    'candidate_validated',
    'candidate_cancelled',
    'activated',
    'health_checked'
);


--
-- Name: system_setting_audit_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_setting_audit_source AS ENUM (
    'admin_api',
    'application_migration',
    'system'
);


--
-- Name: system_setting_health_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_setting_health_status AS ENUM (
    'healthy',
    'invalid',
    'unavailable'
);


--
-- Name: system_setting_section; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_setting_section AS ENUM (
    'platform_github_app',
    'platform_runtime',
    'external_channel_files'
);


--
-- Name: system_setting_validation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_setting_validation_status AS ENUM (
    'pending',
    'valid',
    'invalid',
    'unavailable'
);


--
-- Name: system_user_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.system_user_role AS ENUM (
    'system_admin'
);


--
-- Name: toolkit_scope_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.toolkit_scope_type AS ENUM (
    'workspace'
);


--
-- Name: workspace_user_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.workspace_user_role AS ENUM (
    'owner',
    'manager',
    'member'
);


--
-- Name: xai_oauth_connection_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.xai_oauth_connection_method AS ENUM (
    'device'
);


--
-- Name: xai_oauth_session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.xai_oauth_session_status AS ENUM (
    'pending',
    'connected',
    'cancelled',
    'expired',
    'failed'
);


--
-- Name: initialize_agent_runtime_connection_generation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.initialize_agent_runtime_connection_generation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            BEGIN
              INSERT INTO runtime_connection_generations (
                connection_kind,
                subject_id,
                high_water_generation,
                accepted_generation
              ) VALUES (
                'runner'::runtime_connection_authority_kind,
                NEW.id,
                0,
                0
              );
              RETURN NEW;
            END;
            $$;


--
-- Name: initialize_runtime_provider_connection_generation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.initialize_runtime_provider_connection_generation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            BEGIN
              INSERT INTO runtime_connection_generations (
                connection_kind,
                subject_id,
                high_water_generation,
                accepted_generation
              ) VALUES (
                'provider'::runtime_connection_authority_kind,
                NEW.id,
                0,
                0
              );
              RETURN NEW;
            END;
            $$;


--
-- Name: preserve_external_channel_route_agent_snapshot(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.preserve_external_channel_route_agent_snapshot() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.agent_id_snapshot IS NULL THEN
                    NEW.agent_id_snapshot := NEW.agent_id;
                END IF;
                IF NEW.agent_id_snapshot IS NULL
                   OR NEW.agent_id_snapshot IS DISTINCT FROM NEW.agent_id THEN
                    RAISE EXCEPTION
                        'External Channel route Agent snapshot must match Agent';
                END IF;
            ELSIF NEW.agent_id_snapshot
                    IS DISTINCT FROM OLD.agent_id_snapshot THEN
                RAISE EXCEPTION
                    'External Channel route Agent snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: prevent_external_channel_connection_app_mode_update(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_external_channel_connection_app_mode_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            BEGIN
                IF NEW.app_mode IS DISTINCT FROM OLD.app_mode THEN
                    RAISE EXCEPTION 'External Channel App mode is immutable';
                END IF;
                RETURN NEW;
            END;
            $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: action_execution_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_execution_events (
    id character varying(32) NOT NULL,
    action_execution_id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    sequence integer NOT NULL,
    kind public.action_execution_event_kind NOT NULL,
    step_key text,
    command_argv text[],
    content text,
    exit_code integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: action_executions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.action_executions (
    id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    mailbox_item_id character varying(32) NOT NULL,
    action_type text NOT NULL,
    status public.action_execution_status DEFAULT 'pending'::public.action_execution_status NOT NULL,
    failure_summary text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    failed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    action jsonb NOT NULL,
    owner_generation bigint NOT NULL,
    cancelled_at timestamp with time zone,
    cancellation_summary text,
    sender_user_id character varying(32),
    result jsonb
);


--
-- Name: agent_admins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_admins (
    id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    workspace_user_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_automatic_project_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_automatic_project_items (
    agent_id character varying(32) NOT NULL,
    path text NOT NULL,
    "position" integer NOT NULL,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_automatic_project_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_automatic_project_settings (
    agent_id character varying(32) NOT NULL,
    revision integer DEFAULT 1 NOT NULL,
    updated_by_workspace_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_agent_automatic_project_settings_revision_positive CHECK ((revision >= 1))
);


--
-- Name: agent_avatar_cleanup_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_avatar_cleanup_jobs (
    id character varying(32) NOT NULL,
    avatar jsonb NOT NULL,
    agent_id character varying(32),
    attempt_count integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now(),
    lease_token character varying(120),
    lease_until timestamp with time zone,
    last_failure_kind character varying(120),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_agent_avatar_cleanup_jobs_attempt_count_nonnegative CHECK ((attempt_count >= 0))
);


--
-- Name: agent_decommission_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_decommission_jobs (
    id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    status public.agent_decommission_status DEFAULT 'pending'::public.agent_decommission_status NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    lease_owner character varying(120),
    lease_until timestamp with time zone,
    next_attempt_at timestamp with time zone,
    last_error_kind character varying(120),
    last_error_summary text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    requested_by_workspace_user_id character varying(32)
);


--
-- Name: agent_memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_memories (
    id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    user_id character varying(32),
    scope public.memory_scope NOT NULL,
    type character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    description text NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_project_catalog_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_project_catalog_entries (
    agent_id character varying(32) NOT NULL,
    path text NOT NULL,
    status public.agent_project_catalog_status DEFAULT 'unchecked'::public.agent_project_catalog_status NOT NULL,
    status_detail text,
    checked_at timestamp with time zone,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_project_defaults; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_project_defaults (
    agent_id character varying(32) NOT NULL,
    path text NOT NULL,
    "position" integer NOT NULL,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    item_type public.agent_project_default_item_type NOT NULL
);


--
-- Name: agent_project_presets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_project_presets (
    agent_id character varying(32) NOT NULL,
    path text NOT NULL,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_run_input_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_input_events (
    agent_run_id character varying(32) NOT NULL,
    event_id character varying(32) NOT NULL,
    input_order integer NOT NULL,
    CONSTRAINT ck_agent_run_input_events_input_order CHECK ((input_order >= 0))
);


--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    phase public.agent_run_phase DEFAULT 'idle'::public.agent_run_phase NOT NULL,
    status public.agent_run_status DEFAULT 'running'::public.agent_run_status NOT NULL,
    active_tool_calls jsonb DEFAULT '[]'::jsonb NOT NULL,
    last_completed_event_id character varying(32),
    stop_requested_at timestamp with time zone,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    run_index integer NOT NULL,
    retry_state jsonb,
    terminal_result_event_id character varying(32),
    terminal_result_message text,
    parent_agent_run_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    model_call_started_at timestamp with time zone,
    parent_result_delivery_state public.agent_run_parent_result_delivery_state,
    parent_result_mailbox_item_id character varying(32),
    parent_result_enqueued_at timestamp with time zone,
    vfs_projection jsonb,
    scheduled_task_cycle_id character varying(32),
    requested_model_target_label character varying(80),
    requested_reasoning_effort public.model_reasoning_effort,
    requested_enabled_execution_options jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_agent_runs_requested_profile CHECK (((requested_model_target_label IS NOT NULL) OR ((requested_reasoning_effort IS NULL) AND (requested_enabled_execution_options = '[]'::jsonb))))
);


--
-- Name: agent_runtime_add_receipts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runtime_add_receipts (
    agent_id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    idempotency_key character varying(120) NOT NULL,
    workspace_runtime_profile_id character varying(32) NOT NULL,
    expected_capability_version bigint NOT NULL,
    committed_capability_version bigint NOT NULL,
    committed_runtime_profile_selection_version bigint NOT NULL,
    agent_runtime_id character varying(32) NOT NULL,
    runtime_desired_generation bigint NOT NULL,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    runtime_configuration_sequence bigint NOT NULL,
    runtime_configuration_digest character varying(64) NOT NULL,
    CONSTRAINT ck_agent_runtime_add_receipts_capability_versions CHECK (((expected_capability_version >= 1) AND (committed_capability_version = (expected_capability_version + 1)))),
    CONSTRAINT ck_agent_runtime_add_receipts_configuration_sequence CHECK ((runtime_configuration_sequence >= 1)),
    CONSTRAINT ck_agent_runtime_add_receipts_profile_version CHECK ((committed_runtime_profile_selection_version >= 2)),
    CONSTRAINT ck_agent_runtime_add_receipts_runtime_generation CHECK ((runtime_desired_generation >= 0))
);


--
-- Name: agent_runtime_removal_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runtime_removal_operations (
    agent_id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    requested_by_workspace_user_id character varying(32),
    idempotency_key character varying(120) NOT NULL,
    expected_capability_version bigint NOT NULL,
    committed_capability_version bigint NOT NULL,
    agent_runtime_id character varying(32),
    confirmed_at timestamp with time zone NOT NULL,
    destructive_scope_version integer NOT NULL,
    id character varying(32) NOT NULL,
    status public.agent_runtime_removal_status DEFAULT 'pending'::public.agent_runtime_removal_status NOT NULL,
    stage public.agent_runtime_removal_stage DEFAULT 'fencing'::public.agent_runtime_removal_stage NOT NULL,
    active_root_session_count integer DEFAULT 0 NOT NULL,
    active_subagent_count integer DEFAULT 0 NOT NULL,
    active_run_count integer DEFAULT 0 NOT NULL,
    queued_runtime_action_count integer DEFAULT 0 NOT NULL,
    cleanup_cursor_context_id character varying(32),
    cleanup_scanned_context_count integer DEFAULT 0 NOT NULL,
    cleanup_invalidated_context_count integer DEFAULT 0 NOT NULL,
    product_cleanup_completed_at timestamp with time zone,
    physical_deletion_required boolean,
    target_terminal_delete_generation bigint,
    physical_delete_requested_at timestamp with time zone,
    physical_delete_acknowledgement_kind public.runtime_terminal_delete_acknowledgement_kind,
    physical_delete_acknowledged_at timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    lease_owner character varying(120),
    lease_until timestamp with time zone,
    next_attempt_at timestamp with time zone,
    last_error_kind character varying(120),
    last_error_summary text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_agent_runtime_removal_operations_acknowledgement CHECK ((((physical_delete_acknowledged_at IS NULL) AND (physical_delete_acknowledgement_kind IS NULL)) OR ((physical_delete_acknowledged_at IS NOT NULL) AND (physical_delete_acknowledgement_kind IS NOT NULL)))),
    CONSTRAINT ck_agent_runtime_removal_operations_capability_versions CHECK (((expected_capability_version >= 1) AND (committed_capability_version > expected_capability_version))),
    CONSTRAINT ck_agent_runtime_removal_operations_completion CHECK ((((status = 'completed'::public.agent_runtime_removal_status) AND (stage = 'completed'::public.agent_runtime_removal_stage) AND (completed_at IS NOT NULL) AND (product_cleanup_completed_at IS NOT NULL) AND (physical_deletion_required IS NOT NULL) AND ((physical_deletion_required = false) OR (physical_delete_acknowledged_at IS NOT NULL))) OR ((status <> 'completed'::public.agent_runtime_removal_status) AND (stage <> 'completed'::public.agent_runtime_removal_stage) AND (completed_at IS NULL)))),
    CONSTRAINT ck_agent_runtime_removal_operations_nonnegative_counts CHECK (((active_root_session_count >= 0) AND (active_subagent_count >= 0) AND (active_run_count >= 0) AND (queued_runtime_action_count >= 0) AND (cleanup_scanned_context_count >= 0) AND (cleanup_invalidated_context_count >= 0) AND (cleanup_invalidated_context_count <= cleanup_scanned_context_count))),
    CONSTRAINT ck_agent_runtime_removal_operations_physical_target CHECK ((((physical_deletion_required IS NULL) AND (target_terminal_delete_generation IS NULL) AND (physical_delete_requested_at IS NULL) AND (physical_delete_acknowledged_at IS NULL)) OR ((physical_deletion_required = false) AND (target_terminal_delete_generation IS NULL) AND (physical_delete_requested_at IS NULL) AND (physical_delete_acknowledged_at IS NULL)) OR ((physical_deletion_required = true) AND (target_terminal_delete_generation IS NOT NULL) AND (physical_delete_requested_at IS NOT NULL)))),
    CONSTRAINT ck_agent_runtime_removal_operations_scope_version CHECK ((destructive_scope_version >= 1)),
    CONSTRAINT ck_agent_runtime_removal_operations_target_generation CHECK (((target_terminal_delete_generation IS NULL) OR (target_terminal_delete_generation >= 1)))
);


--
-- Name: agent_runtimes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runtimes (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    runtime_provider_id character varying(120),
    desired_state public.runtime_desired_state DEFAULT 'stopped'::public.runtime_desired_state NOT NULL,
    desired_generation integer DEFAULT 0 NOT NULL,
    last_lifecycle_command public.runtime_lifecycle_command_type,
    reset_final_desired_state public.runtime_desired_state,
    provider_observed_state public.runtime_provider_observed_state DEFAULT 'unknown'::public.runtime_provider_observed_state NOT NULL,
    provider_observed_generation integer DEFAULT 0 NOT NULL,
    provider_connection_state public.runtime_provider_connection_state DEFAULT 'disconnected'::public.runtime_provider_connection_state NOT NULL,
    runner_state public.runtime_runner_state DEFAULT 'unknown'::public.runtime_runner_state NOT NULL,
    runner_generation bigint DEFAULT 0 NOT NULL,
    workspace_path text,
    failure_generation integer,
    failure_code character varying(120),
    failure_message text,
    last_state_change_at timestamp with time zone,
    last_lifecycle_dispatch_generation integer DEFAULT 0 NOT NULL,
    provider_observed_at timestamp with time zone,
    provider_observe_requested_at timestamp with time zone,
    provider_generation bigint DEFAULT 0 NOT NULL,
    terminal_delete_requested_generation integer,
    terminal_delete_acknowledged_generation integer,
    terminal_delete_acknowledged_at timestamp with time zone,
    runtime_provider_resource_id character varying(32),
    provider_binding_origin public.runtime_provider_binding_origin,
    provider_binding_evidence jsonb,
    terminal_delete_acknowledgement_kind public.runtime_terminal_delete_acknowledgement_kind,
    configuration_sequence bigint DEFAULT '0'::bigint NOT NULL,
    CONSTRAINT ck_agent_runtimes_terminal_delete_acknowledgement CHECK ((((terminal_delete_acknowledged_generation IS NULL) AND (terminal_delete_acknowledged_at IS NULL) AND (terminal_delete_acknowledgement_kind IS NULL)) OR ((terminal_delete_acknowledged_generation IS NOT NULL) AND (terminal_delete_acknowledged_at IS NOT NULL) AND (terminal_delete_acknowledgement_kind IS NOT NULL))))
);


--
-- Name: agent_session_system_prompt_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_session_system_prompt_snapshots (
    session_id character varying(32) NOT NULL,
    system_prompt jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_session_unread_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_session_unread_runs (
    session_id character varying(32) NOT NULL,
    run_id character varying(32) NOT NULL,
    run_index bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_agent_session_unread_runs_run_index_positive CHECK ((run_index > 0))
);


--
-- Name: agent_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_sessions (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    status public.agent_session_status NOT NULL,
    start_reason public.agent_session_start_reason NOT NULL,
    end_reason public.agent_session_end_reason,
    model_input_head_event_id character varying(32),
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    lifecycle_started_at timestamp with time zone,
    run_state public.agent_session_run_state DEFAULT 'idle'::public.agent_session_run_state NOT NULL,
    run_heartbeat_at timestamp with time zone DEFAULT now() NOT NULL,
    pending_command_id character varying(32),
    pending_command_name character varying(120),
    pending_command_payload jsonb,
    pending_command_requester_user_id character varying(32),
    pending_command_created_at timestamp with time zone,
    stop_requested_at timestamp with time zone,
    stop_requester_user_id character varying(32),
    stop_request_id character varying(32),
    primary_kind public.agent_session_primary_kind,
    title character varying(200),
    title_source public.agent_session_title_source,
    title_generated_at timestamp with time zone,
    title_generation_event_id character varying(32),
    last_user_input_at timestamp with time zone DEFAULT now() NOT NULL,
    model_file_gc_cursor_event_id character varying(32),
    model_file_gc_updated_at timestamp with time zone,
    handle character varying(120) NOT NULL,
    session_kind public.agent_session_kind NOT NULL,
    current_model_target_label character varying(80),
    current_model_selection jsonb,
    current_reasoning_effort public.model_reasoning_effort,
    current_effective_context_window_tokens integer,
    current_effective_auto_compaction_threshold_tokens integer,
    current_inference_resolved_at timestamp with time zone,
    owner_generation bigint DEFAULT '0'::bigint NOT NULL,
    current_model_settings jsonb,
    archived_at timestamp with time zone,
    purge_after timestamp with time zone,
    archive_policy_revision bigint,
    archive_retention_days_snapshot integer,
    pending_idle_continuation_run_id character varying(32),
    last_activity_at timestamp with time zone DEFAULT now() NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    product_mode public.agent_session_product_mode,
    associated_user_id character varying(32),
    applied_model_target_label character varying(80),
    applied_reasoning_effort public.model_reasoning_effort,
    current_enabled_execution_options jsonb DEFAULT '[]'::jsonb NOT NULL,
    applied_enabled_execution_options jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_agent_sessions_applied_inference_profile CHECK (((applied_model_target_label IS NOT NULL) OR ((applied_reasoning_effort IS NULL) AND (applied_enabled_execution_options = '[]'::jsonb)))),
    CONSTRAINT ck_agent_sessions_current_compaction_threshold CHECK (((current_effective_auto_compaction_threshold_tokens IS NULL) OR (current_effective_auto_compaction_threshold_tokens > 0))),
    CONSTRAINT ck_agent_sessions_current_context_window CHECK (((current_effective_context_window_tokens IS NULL) OR (current_effective_context_window_tokens > 0))),
    CONSTRAINT ck_agent_sessions_current_inference_state CHECK ((((current_model_target_label IS NULL) AND (current_model_selection IS NULL) AND (current_model_settings IS NULL) AND (current_reasoning_effort IS NULL) AND (current_enabled_execution_options = '[]'::jsonb) AND (current_effective_context_window_tokens IS NULL) AND (current_effective_auto_compaction_threshold_tokens IS NULL) AND (current_inference_resolved_at IS NULL)) OR ((current_model_target_label IS NOT NULL) AND (current_model_selection IS NOT NULL) AND (current_model_settings IS NOT NULL) AND (current_effective_context_window_tokens IS NOT NULL) AND (current_effective_auto_compaction_threshold_tokens IS NOT NULL) AND (current_inference_resolved_at IS NOT NULL)))),
    CONSTRAINT ck_agent_sessions_product_mode_ownership CHECK ((((session_kind = 'root'::public.agent_session_kind) AND (product_mode IS NOT NULL) AND (((product_mode = 'team'::public.agent_session_product_mode) AND (associated_user_id IS NULL)) OR ((product_mode = 'user'::public.agent_session_product_mode) AND (associated_user_id IS NOT NULL) AND (primary_kind IS NULL)))) OR ((session_kind = 'subagent'::public.agent_session_kind) AND (product_mode IS NULL) AND (associated_user_id IS NULL) AND (primary_kind IS NULL))))
);


--
-- Name: agent_toolkits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_toolkits (
    id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    toolkit_id character varying(32) NOT NULL,
    toolkit_type character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    model_parameters jsonb,
    system_prompt text,
    enabled boolean DEFAULT true NOT NULL,
    type public.agent_type DEFAULT 'public'::public.agent_type NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    memory_enabled boolean DEFAULT true NOT NULL,
    avatar jsonb,
    max_turns integer,
    model_selection jsonb NOT NULL,
    lightweight_model_selection jsonb NOT NULL,
    subagent_settings jsonb DEFAULT '{"max_depth": 1, "max_subagents": 3}'::jsonb NOT NULL,
    selectable_model_options jsonb NOT NULL,
    main_model_label character varying(80) NOT NULL,
    lightweight_model_label character varying(80) NOT NULL,
    tool_search_enabled boolean DEFAULT true NOT NULL,
    lifecycle_status public.agent_lifecycle_status DEFAULT 'active'::public.agent_lifecycle_status NOT NULL,
    auto_archive_ttl_days integer DEFAULT 30 NOT NULL,
    runtime_profile_id character varying(32),
    runtime_profile_selection_version integer DEFAULT 1 NOT NULL,
    external_channel_default_response_mode public.external_channel_response_mode DEFAULT 'all_messages'::public.external_channel_response_mode NOT NULL,
    runtime_capability public.agent_runtime_capability DEFAULT 'managed'::public.agent_runtime_capability NOT NULL,
    runtime_capability_version integer DEFAULT 1 NOT NULL,
    terminal_enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_agents_auto_archive_ttl_days_positive CHECK ((auto_archive_ttl_days > 0)),
    CONSTRAINT ck_agents_max_turns_positive CHECK (((max_turns IS NULL) OR (max_turns > 0))),
    CONSTRAINT ck_agents_model_not_null CHECK (((model_selection IS NOT NULL) AND (lightweight_model_selection IS NOT NULL))),
    CONSTRAINT ck_agents_runtime_capability_profile CHECK (((runtime_capability = 'managed'::public.agent_runtime_capability) OR (runtime_profile_id IS NULL))),
    CONSTRAINT ck_agents_runtime_capability_version_positive CHECK ((runtime_capability_version >= 1)),
    CONSTRAINT ck_agents_runtime_profile_selection_version_positive CHECK ((runtime_profile_selection_version >= 1)),
    CONSTRAINT ck_agents_selectable_model_options_shape CHECK (((jsonb_typeof(selectable_model_options) = 'array'::text) AND ((jsonb_array_length(selectable_model_options) >= 1) AND (jsonb_array_length(selectable_model_options) <= 10)))),
    CONSTRAINT ck_agents_subagent_settings_shape CHECK (((jsonb_typeof(subagent_settings) = 'object'::text) AND (subagent_settings ? 'max_subagents'::text) AND (subagent_settings ? 'max_depth'::text) AND (jsonb_typeof((subagent_settings -> 'max_subagents'::text)) = 'number'::text) AND (jsonb_typeof((subagent_settings -> 'max_depth'::text)) = 'number'::text) AND (((subagent_settings ->> 'max_subagents'::text))::integer >= 0) AND (((subagent_settings ->> 'max_depth'::text))::integer >= 0)))
);


--
-- Name: archived_session_purge_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.archived_session_purge_jobs (
    id character varying(32) NOT NULL,
    root_session_id character varying(32) NOT NULL,
    eligible_at timestamp with time zone NOT NULL,
    policy_revision bigint NOT NULL,
    status public.archived_session_purge_status DEFAULT 'pending'::public.archived_session_purge_status NOT NULL,
    fencing_started_at timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    lease_owner character varying(120),
    lease_until timestamp with time zone,
    next_attempt_at timestamp with time zone,
    last_error_kind character varying(120),
    last_error_summary text,
    model_file_count integer DEFAULT 0 NOT NULL,
    artifact_count integer DEFAULT 0 NOT NULL,
    exchange_file_count integer DEFAULT 0 NOT NULL,
    worktree_count integer DEFAULT 0 NOT NULL,
    started_at timestamp with time zone,
    last_attempt_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_error_participant_key character varying(120),
    last_error_phase public.archived_session_purge_participant_phase
);


--
-- Name: archived_session_purge_participant_executions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.archived_session_purge_participant_executions (
    purge_job_id character varying(32) NOT NULL,
    participant_key character varying(120) NOT NULL,
    policy_version integer NOT NULL,
    phase public.archived_session_purge_participant_phase DEFAULT 'pending'::public.archived_session_purge_participant_phase NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    blocked_by_participant_key character varying(120),
    last_error_kind character varying(120),
    last_error_summary text,
    operational_summary jsonb,
    prepared_at timestamp with time zone,
    cleanup_completed_at timestamp with time zone,
    verified_at timestamp with time zone,
    last_attempt_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_archived_purge_part_exec_attempt_nonnegative CHECK ((attempt_count >= 0)),
    CONSTRAINT ck_archived_purge_part_exec_policy_positive CHECK ((policy_version >= 1))
);


--
-- Name: archived_session_retention_applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.archived_session_retention_applications (
    id character varying(32) NOT NULL,
    target_revision bigint NOT NULL,
    target_retention_days integer,
    requested_by_user_id character varying(32),
    status public.archived_session_retention_application_status DEFAULT 'pending'::public.archived_session_retention_application_status NOT NULL,
    cursor_session_id character varying(32),
    affected_count integer DEFAULT 0 NOT NULL,
    immediately_eligible_count integer DEFAULT 0 NOT NULL,
    cancelled_count integer DEFAULT 0 NOT NULL,
    scheduled_count integer DEFAULT 0 NOT NULL,
    skipped_count integer DEFAULT 0 NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    lease_owner character varying(120),
    lease_until timestamp with time zone,
    next_attempt_at timestamp with time zone,
    last_error_kind character varying(120),
    last_error_summary text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_archived_session_retention_applications_target_days CHECK (((target_retention_days IS NULL) OR (target_retention_days >= 0)))
);


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    created_run_id character varying(32) NOT NULL,
    created_run_index integer NOT NULL,
    name character varying(255) NOT NULL,
    media_type character varying(255) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_key character varying(1024) NOT NULL,
    status public.artifact_status DEFAULT 'available'::public.artifact_status NOT NULL,
    sha256 character varying(64),
    source_tool_name character varying(255),
    source_call_id character varying(255),
    source_part_index integer,
    description text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expired_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    blob_deleted_at timestamp with time zone
);


--
-- Name: chat_write_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_write_requests (
    id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    requester_user_id character varying(32) NOT NULL,
    client_request_id character varying(64) NOT NULL,
    write_type public.chat_write_request_type NOT NULL,
    accepted_type public.chat_write_request_type NOT NULL,
    accepted_id character varying(128) NOT NULL,
    history_reload_required boolean NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    creation_agent_id character varying(32)
);


--
-- Name: chatgpt_oauth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chatgpt_oauth_sessions (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    method public.chatgpt_oauth_connection_method NOT NULL,
    state character varying(128) NOT NULL,
    encrypted_code_verifier text NOT NULL,
    redirect_uri text NOT NULL,
    encrypted_device_auth_id text,
    user_code character varying(64),
    verification_uri text,
    interval_seconds integer,
    status public.chatgpt_oauth_session_status DEFAULT 'pending'::public.chatgpt_oauth_session_status NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: email_verifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_verifications (
    id character varying(32) NOT NULL,
    email character varying(255) NOT NULL,
    code character varying(6) NOT NULL,
    csrf_token character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    verified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    kind public.event_kind NOT NULL,
    payload jsonb NOT NULL,
    external_id text,
    adapter text,
    provider text,
    model text,
    native_format text,
    schema_version character varying(20) DEFAULT '1'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reverted boolean DEFAULT false NOT NULL
);


--
-- Name: exchange_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exchange_files (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    origin_type public.exchange_file_origin NOT NULL,
    object_key character varying(1024) NOT NULL,
    filename character varying(255) NOT NULL,
    media_type character varying(255) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    created_by_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    preview_thumbnail_file_id character varying(32),
    status public.exchange_file_status DEFAULT 'available'::public.exchange_file_status NOT NULL,
    preview_title character varying(255),
    preview_summary text,
    preview_thumbnail_media_type character varying(255),
    preview_thumbnail_width integer,
    preview_thumbnail_height integer,
    preview_generated_at timestamp with time zone,
    expires_at timestamp with time zone DEFAULT (now() + '30 days'::interval) NOT NULL,
    expired_at timestamp with time zone,
    blob_deleted_at timestamp with time zone,
    retention_root_session_id character varying(32),
    retention_bound_at timestamp with time zone,
    provenance_kind public.exchange_file_provenance_kind,
    source_user_id character varying(32),
    source_agent_id character varying(32),
    source_run_id character varying(32),
    source_tool_name character varying(255),
    source_provider character varying(255),
    source_exchange_file_id character varying(32)
);


--
-- Name: external_channel_access_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_access_grants (
    id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    principal_id character varying(32) NOT NULL,
    scope public.external_channel_access_grant_scope NOT NULL,
    granted_by_user_id character varying(32) NOT NULL,
    agent_session_id character varying(32),
    source_access_request_id character varying(32),
    revoked_by_user_id character varying(32),
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_external_channel_access_grants_scope_session CHECK ((((scope = 'agent'::public.external_channel_access_grant_scope) AND (agent_session_id IS NULL)) OR ((scope = 'session'::public.external_channel_access_grant_scope) AND (agent_session_id IS NOT NULL))))
);


--
-- Name: external_channel_access_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_access_requests (
    id character varying(32) NOT NULL,
    route_id character varying(32) NOT NULL,
    resource_id character varying(32) NOT NULL,
    principal_id character varying(32) NOT NULL,
    status public.external_channel_access_request_status DEFAULT 'pending'::public.external_channel_access_request_status NOT NULL,
    decision_policy_snapshot jsonb NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    agent_session_id character varying(32),
    decided_by_user_id character varying(32),
    decision_summary text,
    decided_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    conversation_position_id character varying(32),
    range_start_position text,
    trigger_position text,
    connection_id character varying(32),
    trigger_provider_message_key text NOT NULL,
    setup_claim_id character varying(32),
    control_provider_message_key character varying(255),
    control_projection_status public.external_channel_work_projection_status,
    source_resource_id character varying(32) NOT NULL,
    CONSTRAINT ck_external_channel_access_requests_pending_boundary CHECK (((status <> 'pending'::public.external_channel_access_request_status) OR ((connection_id IS NOT NULL) AND (conversation_position_id IS NOT NULL) AND (trigger_position IS NOT NULL))))
);


--
-- Name: external_channel_agent_route_bot_policy_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_agent_route_bot_policy_archive (
    route_id character varying(32) NOT NULL,
    allow_bot_messages boolean NOT NULL
);


--
-- Name: external_channel_agent_routes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_agent_routes (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    agent_id character varying(32),
    route_mode public.external_channel_route_mode DEFAULT 'dedicated'::public.external_channel_route_mode NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    connection_app_mode public.external_channel_app_mode DEFAULT 'single'::public.external_channel_app_mode NOT NULL,
    catalog_status public.external_channel_route_catalog_status DEFAULT 'available'::public.external_channel_route_catalog_status NOT NULL,
    catalog_removed_at timestamp with time zone,
    catalog_removed_by_user_id character varying(32),
    agent_id_snapshot character varying(32) NOT NULL,
    open_access_enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_external_channel_agent_routes_agent_snapshot CHECK (((agent_id IS NULL) OR ((agent_id)::text = (agent_id_snapshot)::text))),
    CONSTRAINT ck_external_channel_agent_routes_available_agent CHECK (((catalog_status = 'removed'::public.external_channel_route_catalog_status) OR (agent_id IS NOT NULL)))
);


--
-- Name: external_channel_app_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_app_claims (
    id character varying(32) NOT NULL,
    provider public.external_channel_provider NOT NULL,
    provider_app_id character varying(255) NOT NULL,
    connection_id character varying(32) NOT NULL,
    claim_generation integer DEFAULT 1 NOT NULL,
    acquired_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: external_channel_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_bindings (
    id character varying(32) NOT NULL,
    resource_id character varying(32) NOT NULL,
    route_id character varying(32) NOT NULL,
    agent_session_id character varying(32) NOT NULL,
    connected_at timestamp with time zone DEFAULT now() NOT NULL,
    disconnected_at timestamp with time zone,
    disconnect_reason character varying(120),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    response_mode public.external_channel_response_mode DEFAULT 'all_messages'::public.external_channel_response_mode NOT NULL
);


--
-- Name: external_channel_blocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_blocks (
    id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    principal_id character varying(32) NOT NULL,
    blocked_by_user_id character varying(32) NOT NULL,
    reason text,
    removed_by_user_id character varying(32),
    removed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: external_channel_channel_defaults; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_channel_defaults (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    provider_channel_id character varying(255) NOT NULL,
    route_id character varying(32) NOT NULL,
    status public.external_channel_channel_default_status DEFAULT 'active'::public.external_channel_channel_default_status NOT NULL,
    configured_by_user_id character varying(32),
    invalidated_at timestamp with time zone,
    invalidation_reason character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    configured_by_principal_id character varying(32),
    CONSTRAINT ck_external_channel_channel_defaults_configured_actor CHECK ((num_nonnulls(configured_by_user_id, configured_by_principal_id) = 1))
);


--
-- Name: external_channel_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_connections (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    provider public.external_channel_provider NOT NULL,
    transport public.external_channel_transport NOT NULL,
    status public.external_channel_connection_status DEFAULT 'configuring'::public.external_channel_connection_status NOT NULL,
    provider_app_id character varying(255),
    provider_tenant_id character varying(255),
    provider_bot_user_id character varying(255),
    http_callback_selector_hash character varying(128),
    encrypted_credentials text,
    capabilities jsonb,
    provider_config jsonb,
    last_verified_at timestamp with time zone,
    last_health_at timestamp with time zone,
    disconnected_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    socket_lease_owner character varying(255),
    socket_lease_until timestamp with time zone,
    socket_heartbeat_at timestamp with time zone,
    socket_gap_detected_at timestamp with time zone,
    socket_gap_reason character varying(255),
    app_mode public.external_channel_app_mode DEFAULT 'single'::public.external_channel_app_mode NOT NULL,
    ingress_profile public.external_channel_ingress_profile NOT NULL,
    configuration_generation integer DEFAULT 1 NOT NULL,
    last_health_code character varying(64),
    slack_presence_lease_owner character varying(255),
    slack_presence_lease_until timestamp with time zone,
    slack_presence_heartbeat_at timestamp with time zone
);


--
-- Name: external_channel_conversation_positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_conversation_positions (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    scope_kind public.external_channel_conversation_scope_kind NOT NULL,
    provider_channel_id text NOT NULL,
    provider_thread_key text,
    read_through_position text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_external_channel_conversation_positions_scope_key CHECK ((((scope_kind = 'parent_channel'::public.external_channel_conversation_scope_kind) AND (provider_thread_key IS NULL)) OR ((scope_kind = 'thread'::public.external_channel_conversation_scope_kind) AND (provider_thread_key IS NOT NULL))))
);


--
-- Name: external_channel_ingress_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_ingress_items (
    id character varying(32) NOT NULL,
    queue_key character varying(32) NOT NULL,
    deduplication_key character varying(64) NOT NULL,
    provider_event_id character varying(255) NOT NULL,
    connection_id character varying(32) NOT NULL,
    provider public.external_channel_provider NOT NULL,
    ingress_profile public.external_channel_ingress_profile NOT NULL,
    configuration_generation integer NOT NULL,
    authority_kind public.external_channel_ingress_authority_kind NOT NULL,
    authority_lease_owner character varying(255),
    authority_lease_generation integer,
    provider_event_type character varying(120) NOT NULL,
    provider_tenant_id character varying(255) NOT NULL,
    scope_kind public.external_channel_conversation_scope_kind NOT NULL,
    provider_channel_id text NOT NULL,
    provider_parent_channel_id text,
    provider_thread_key text,
    delivery_thread_key text,
    provider_resource_key text NOT NULL,
    conversation_position_id character varying(32) NOT NULL,
    principal_id character varying(32) NOT NULL,
    trigger_provider_message_key text NOT NULL,
    trigger_provider_message_id text NOT NULL,
    trigger_position text NOT NULL,
    provider_user_id character varying(255),
    invocation boolean NOT NULL,
    invocation_id character varying(255) NOT NULL,
    initial_title_eligible boolean NOT NULL,
    state public.external_channel_ingress_item_state DEFAULT 'pending'::public.external_channel_ingress_item_state NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone,
    processing_owner character varying(255),
    processing_generation integer,
    batch_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    owner_id character varying(32) NOT NULL,
    source_resource_id character varying(32) NOT NULL,
    expected_file_count integer,
    CONSTRAINT ck_external_channel_ingress_items_active_state CHECK ((((state = 'pending'::public.external_channel_ingress_item_state) AND (next_attempt_at IS NULL) AND (processing_owner IS NULL) AND (processing_generation IS NULL) AND (batch_id IS NULL)) OR ((state = 'retry_waiting'::public.external_channel_ingress_item_state) AND (next_attempt_at IS NOT NULL) AND (processing_owner IS NULL) AND (processing_generation IS NULL) AND (batch_id IS NULL)) OR ((state = 'processing'::public.external_channel_ingress_item_state) AND (next_attempt_at IS NULL) AND (processing_owner IS NOT NULL) AND (processing_generation IS NOT NULL) AND (batch_id IS NOT NULL)))),
    CONSTRAINT ck_external_channel_ingress_items_attempt_count CHECK (((attempt_count >= 0) AND (attempt_count <= 5))),
    CONSTRAINT ck_external_channel_ingress_items_authority CHECK ((((authority_kind = 'lease'::public.external_channel_ingress_authority_kind) AND (authority_lease_owner IS NOT NULL)) OR ((authority_kind <> 'lease'::public.external_channel_ingress_authority_kind) AND (authority_lease_owner IS NULL) AND (authority_lease_generation IS NULL)))),
    CONSTRAINT ck_external_channel_ingress_items_expected_file_count CHECK (((expected_file_count IS NULL) OR ((expected_file_count >= 0) AND (expected_file_count <= 20)))),
    CONSTRAINT ck_external_channel_ingress_items_scope_key CHECK ((((scope_kind = 'parent_channel'::public.external_channel_conversation_scope_kind) AND (provider_thread_key IS NULL)) OR ((scope_kind = 'thread'::public.external_channel_conversation_scope_kind) AND (provider_thread_key IS NOT NULL))))
);


--
-- Name: external_channel_ingress_leases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_ingress_leases (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    lease_owner character varying(255),
    lease_generation integer DEFAULT 0 NOT NULL,
    lease_until timestamp with time zone,
    heartbeat_at timestamp with time zone,
    required_configuration_generation integer,
    required_app_claim_generation integer,
    gap_detected_at timestamp with time zone,
    gap_reason character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: external_channel_ingress_owners; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_ingress_owners (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    target_resource_id character varying(32) NOT NULL,
    route_id character varying(32) NOT NULL,
    participation_setting_id character varying(32),
    participation_settings_generation integer,
    response_mode public.external_channel_response_mode NOT NULL,
    binding_id character varying(32),
    session_id character varying(32),
    preparation_attempt_count integer DEFAULT 0 NOT NULL,
    preparation_next_attempt_at timestamp with time zone,
    lease_owner character varying(255),
    lease_generation integer DEFAULT 0 NOT NULL,
    lease_acquired_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    first_batch_pending boolean DEFAULT true NOT NULL,
    current_batch_id character varying(32),
    current_batch_started_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_external_channel_ingress_owners_batch CHECK ((((current_batch_id IS NULL) AND (current_batch_started_at IS NULL)) OR ((current_batch_id IS NOT NULL) AND (current_batch_started_at IS NOT NULL) AND (lease_owner IS NOT NULL)))),
    CONSTRAINT ck_external_channel_ingress_owners_lease CHECK ((((lease_owner IS NULL) AND (lease_acquired_at IS NULL) AND (lease_expires_at IS NULL)) OR ((lease_owner IS NOT NULL) AND (lease_acquired_at IS NOT NULL) AND (lease_expires_at IS NOT NULL)))),
    CONSTRAINT ck_external_channel_ingress_owners_preparation_attempt_count CHECK (((preparation_attempt_count >= 0) AND (preparation_attempt_count <= 5))),
    CONSTRAINT ck_external_channel_ingress_owners_ready CHECK ((((binding_id IS NULL) AND (session_id IS NULL)) OR ((binding_id IS NOT NULL) AND (session_id IS NOT NULL)))),
    CONSTRAINT ck_external_channel_ingress_owners_setting CHECK ((((participation_setting_id IS NULL) AND (participation_settings_generation IS NULL)) OR ((participation_setting_id IS NOT NULL) AND (participation_settings_generation IS NOT NULL))))
);


--
-- Name: external_channel_interactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_interactions (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    transport public.external_channel_transport NOT NULL,
    provider_interaction_key character varying(128) NOT NULL,
    interaction_type public.external_channel_interaction_type NOT NULL,
    callback_id character varying(255),
    action_id character varying(255),
    principal_id character varying(32),
    resource_correlation_key character varying(512),
    projection jsonb NOT NULL,
    status public.external_channel_interaction_status DEFAULT 'accepted'::public.external_channel_interaction_status NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    error_kind character varying(120),
    error_summary character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    setup_claim_id character varying(32)
);


--
-- Name: external_channel_participation_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_participation_settings (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    provider_parent_channel_id character varying(255) NOT NULL,
    route_id character varying(32) NOT NULL,
    location public.external_channel_conversation_location NOT NULL,
    response_mode public.external_channel_response_mode NOT NULL,
    settings_generation integer NOT NULL,
    status public.external_channel_participation_setting_status NOT NULL,
    configured_by_user_id character varying(32),
    configured_by_principal_id character varying(32),
    invalidated_at timestamp with time zone,
    invalidation_reason character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_external_channel_participation_invalidation_metadata CHECK ((((status = 'active'::public.external_channel_participation_setting_status) AND (invalidated_at IS NULL) AND (invalidation_reason IS NULL)) OR ((status = 'invalidated'::public.external_channel_participation_setting_status) AND (invalidated_at IS NOT NULL) AND (invalidation_reason IS NOT NULL)))),
    CONSTRAINT ck_external_channel_participation_settings_configured_actor CHECK ((num_nonnulls(configured_by_user_id, configured_by_principal_id) = 1)),
    CONSTRAINT ck_external_channel_participation_settings_positive_generation CHECK ((settings_generation > 0))
);


--
-- Name: external_channel_principals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_principals (
    id character varying(32) NOT NULL,
    provider public.external_channel_provider NOT NULL,
    provider_tenant_id character varying(255) NOT NULL,
    provider_user_id character varying(255) NOT NULL,
    author_type public.external_channel_principal_author_type NOT NULL,
    display_name character varying(255),
    avatar_url text,
    profile jsonb,
    first_observed_at timestamp with time zone DEFAULT now() NOT NULL,
    last_observed_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: external_channel_resources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_resources (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    resource_type public.external_channel_resource_type NOT NULL,
    provider_resource_key text NOT NULL,
    status public.external_channel_resource_status DEFAULT 'active'::public.external_channel_resource_status NOT NULL,
    labels jsonb,
    discovered_at timestamp with time zone DEFAULT now() NOT NULL,
    latest_activity_at timestamp with time zone,
    unavailable_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: external_channel_setup_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_channel_setup_claims (
    id character varying(32) NOT NULL,
    connection_id character varying(32) NOT NULL,
    provider_parent_channel_id character varying(255) NOT NULL,
    route_id character varying(32),
    conversation_position_id character varying(32) NOT NULL,
    source_resource_id character varying(32) NOT NULL,
    principal_id character varying(32) NOT NULL,
    source_projection jsonb NOT NULL,
    source_revision integer NOT NULL,
    claim_generation integer NOT NULL,
    status public.external_channel_setup_claim_status NOT NULL,
    selected_setting_id character varying(32),
    selected_resource_id character varying(32),
    selected_source_revision integer,
    expires_at timestamp with time zone NOT NULL,
    selected_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_external_channel_setup_claims_completed_at CHECK ((((status = 'completed'::public.external_channel_setup_claim_status) AND (completed_at IS NOT NULL)) OR (status <> 'completed'::public.external_channel_setup_claim_status))),
    CONSTRAINT ck_external_channel_setup_claims_positive_revisions CHECK (((source_revision > 0) AND (claim_generation > 0))),
    CONSTRAINT ck_external_channel_setup_claims_selected_source_revision CHECK (((selected_source_revision IS NULL) OR ((selected_source_revision > 0) AND (selected_source_revision <= source_revision)))),
    CONSTRAINT ck_external_channel_setup_claims_selection_metadata CHECK ((((status = ANY (ARRAY['pending_agent'::public.external_channel_setup_claim_status, 'pending_location'::public.external_channel_setup_claim_status])) AND (selected_setting_id IS NULL) AND (selected_resource_id IS NULL) AND (selected_source_revision IS NULL) AND (selected_at IS NULL)) OR ((status = ANY (ARRAY['selected'::public.external_channel_setup_claim_status, 'completed'::public.external_channel_setup_claim_status])) AND (selected_setting_id IS NOT NULL) AND (selected_resource_id IS NOT NULL) AND (selected_source_revision IS NOT NULL) AND (selected_at IS NOT NULL)) OR (status = ANY (ARRAY['expired'::public.external_channel_setup_claim_status, 'invalidated'::public.external_channel_setup_claim_status]))))
);


--
-- Name: git_worktree_path_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.git_worktree_path_claims (
    id character varying(32) NOT NULL,
    agent_runtime_id character varying(32) NOT NULL,
    worktree_path text NOT NULL,
    owner_kind public.git_worktree_path_claim_owner_kind NOT NULL,
    action_execution_id character varying(32),
    root_session_id character varying(32),
    owner_generation bigint,
    discovery_fingerprint text,
    state public.git_worktree_path_claim_state NOT NULL,
    reason_code text,
    summary text,
    lease_until timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: github_user_installations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.github_user_installations (
    id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    installation_id bigint NOT NULL,
    account_login character varying(255) NOT NULL,
    account_type character varying(50) NOT NULL,
    account_avatar_url text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    platform_app_id character varying(64) NOT NULL
);


--
-- Name: kimi_oauth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kimi_oauth_sessions (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    method public.kimi_oauth_connection_method NOT NULL,
    encrypted_device_code text NOT NULL,
    encrypted_device_id text NOT NULL,
    user_code character varying(128) NOT NULL,
    verification_uri text NOT NULL,
    interval_seconds integer NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status public.kimi_oauth_session_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: kubernetes_sandbox_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kubernetes_sandbox_snapshots (
    id character varying(32) NOT NULL,
    image_ref character varying(512) NOT NULL,
    base_image_ref character varying(512) NOT NULL,
    kind public.snapshot_kind NOT NULL,
    size_bytes bigint,
    digest character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    agent_runtime_id character varying(32) NOT NULL
);


--
-- Name: litellm_source_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.litellm_source_snapshots (
    id character varying(32) NOT NULL,
    source_key character varying(120) NOT NULL,
    source_url text,
    source_hash character varying(64) NOT NULL,
    model_count integer NOT NULL,
    litellm_version character varying(80),
    loaded_source character varying(40) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: llm_catalog_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_catalog_entries (
    id character varying(32) NOT NULL,
    catalog_id character varying(32) NOT NULL,
    snapshot_id character varying(32) NOT NULL,
    provider_integration_id character varying(32),
    provider public.llm_provider NOT NULL,
    publisher character varying(120),
    provider_model_identifier character varying(300) NOT NULL,
    lowerer_target public.llm_catalog_lowerer_target NOT NULL,
    runtime_model_identifier character varying(300) NOT NULL,
    display_name character varying(300) NOT NULL,
    family character varying(160),
    normalized_capabilities jsonb NOT NULL,
    lifecycle_status public.llm_model_lifecycle_status NOT NULL,
    visibility_status public.llm_catalog_entry_visibility NOT NULL,
    source_metadata jsonb,
    projection_metadata jsonb,
    hidden_reason character varying(160),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    supported_execution_options jsonb DEFAULT '[]'::jsonb NOT NULL
);


--
-- Name: llm_catalog_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_catalog_snapshots (
    id character varying(32) NOT NULL,
    catalog_id character varying(32) NOT NULL,
    source_snapshot_id character varying(32),
    entry_count integer NOT NULL,
    visible_count integer NOT NULL,
    hidden_count integer NOT NULL,
    diagnostics jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: llm_catalog_sync_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_catalog_sync_attempts (
    id character varying(32) NOT NULL,
    catalog_id character varying(32),
    source_key character varying(120) NOT NULL,
    status public.llm_catalog_attempt_status NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    produced_snapshot_id character varying(32),
    failure_code character varying(120),
    failure_message text,
    action_hint text,
    fetched_count integer NOT NULL,
    matched_count integer NOT NULL,
    skipped_count integer NOT NULL,
    hidden_count integer NOT NULL,
    diagnostics jsonb
);


--
-- Name: llm_catalogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_catalogs (
    id character varying(32) NOT NULL,
    scope public.llm_catalog_scope NOT NULL,
    provider public.llm_provider NOT NULL,
    provider_integration_id character varying(32),
    lowerer_target public.llm_catalog_lowerer_target NOT NULL,
    current_snapshot_id character varying(32),
    latest_attempt_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: llm_provider_integrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_provider_integrations (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    provider public.llm_provider NOT NULL,
    name character varying(255) NOT NULL,
    encrypted_credentials text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    config jsonb
);


--
-- Name: mailbox_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mailbox_items (
    id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    kind public.mailbox_item_kind NOT NULL,
    sender_user_id character varying(32),
    idempotency_key character varying(120),
    requested_model_target_label character varying(80),
    requested_reasoning_effort public.model_reasoning_effort,
    scheduling_mode public.mailbox_item_scheduling_mode NOT NULL,
    payload jsonb NOT NULL,
    order_group character varying(32) NOT NULL,
    order_sequence integer NOT NULL,
    requested_enabled_execution_options jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_mailbox_items_order_sequence CHECK ((order_sequence >= 0)),
    CONSTRAINT ck_mailbox_items_requested_profile CHECK (((requested_model_target_label IS NOT NULL) OR ((requested_reasoning_effort IS NULL) AND (requested_enabled_execution_options = '[]'::jsonb)))),
    CONSTRAINT ck_mailbox_items_sender_user_kind CHECK (((sender_user_id IS NULL) OR (kind = ANY (ARRAY['user_message'::public.mailbox_item_kind, 'action_message'::public.mailbox_item_kind]))))
);


--
-- Name: mcp_oauth_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mcp_oauth_connections (
    id character varying(32) NOT NULL,
    toolkit_id character varying(32) NOT NULL,
    issuer text,
    resource text,
    server_url text NOT NULL,
    authorization_endpoint text NOT NULL,
    token_endpoint text NOT NULL,
    registration_endpoint text,
    encrypted_client_id text NOT NULL,
    encrypted_client_secret text,
    token_endpoint_auth_method character varying(64) NOT NULL,
    scope text,
    encrypted_access_token text,
    encrypted_refresh_token text,
    expires_at timestamp with time zone,
    status public.mcp_oauth_connection_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: model_file_pins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_file_pins (
    model_file_id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    run_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: model_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_files (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    name character varying(255),
    media_type character varying(255) NOT NULL,
    kind character varying(32) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_key character varying(1024) NOT NULL,
    status public.model_file_status DEFAULT 'available'::public.model_file_status NOT NULL,
    normalized_format character varying(32) NOT NULL,
    sha256 character varying(64) NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    created_run_index integer NOT NULL,
    blob_deleted_at timestamp with time zone,
    created_run_id character varying(32)
);


--
-- Name: owner_lifecycle_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owner_lifecycle_jobs (
    id character varying(32) NOT NULL,
    kind public.owner_lifecycle_kind NOT NULL,
    user_id character varying(32) NOT NULL,
    workspace_id character varying(32),
    status public.owner_lifecycle_status DEFAULT 'pending'::public.owner_lifecycle_status NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    lease_owner character varying(120),
    lease_until timestamp with time zone,
    next_attempt_at timestamp with time zone,
    last_error_kind character varying(120),
    last_error_summary text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_owner_lifecycle_jobs_kind_workspace CHECK ((((kind = 'membership_archive'::public.owner_lifecycle_kind) AND (workspace_id IS NOT NULL)) OR ((kind = 'account_purge'::public.owner_lifecycle_kind) AND (workspace_id IS NULL))))
);


--
-- Name: password_logins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_logins (
    id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    password_hash character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: password_reset_token_redemptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_reset_token_redemptions (
    id character varying(32) NOT NULL,
    password_reset_token_id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    redeemed_at timestamp with time zone NOT NULL,
    ip_address character varying(64),
    user_agent text
);


--
-- Name: password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_reset_tokens (
    id character varying(32) NOT NULL,
    token_hash character varying(64) NOT NULL,
    user_id character varying(32) NOT NULL,
    created_by_user_id character varying(32),
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_configuration_reconcile_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_configuration_reconcile_tasks (
    id character varying(32) NOT NULL,
    source_type public.runtime_reconcile_source_kind NOT NULL,
    source_id character varying(120) NOT NULL,
    source_version character varying(120) NOT NULL,
    status public.runtime_reconcile_task_status NOT NULL,
    available_at timestamp with time zone NOT NULL,
    cursor character varying(120),
    attempt integer NOT NULL,
    failure_code character varying(120),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_runtime_configuration_reconcile_tasks_attempt CHECK ((attempt >= 0))
);


--
-- Name: runtime_configuration_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_configuration_states (
    runtime_id character varying(32) NOT NULL,
    desired_sequence bigint NOT NULL,
    desired_status public.runtime_configuration_state_status NOT NULL,
    desired_target_generation bigint NOT NULL,
    desired_digest character varying(64),
    desired_document jsonb,
    desired_reason_code character varying(120),
    provider_reported_digest character varying(64),
    runner_reported_digest character varying(64),
    provider_acknowledged_at timestamp with time zone,
    runner_observed_at timestamp with time zone,
    applied_sequence bigint,
    applied_target_generation bigint,
    applied_digest character varying(64),
    applied_document jsonb,
    applied_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_runtime_configuration_states_applied CHECK ((((applied_sequence IS NULL) AND (applied_target_generation IS NULL) AND (applied_digest IS NULL) AND (applied_document IS NULL) AND (applied_at IS NULL)) OR ((applied_sequence IS NOT NULL) AND (applied_target_generation IS NOT NULL) AND (applied_digest IS NOT NULL) AND (applied_document IS NOT NULL) AND (applied_at IS NOT NULL)))),
    CONSTRAINT ck_runtime_configuration_states_desired CHECK ((((desired_status = 'unconfigured'::public.runtime_configuration_state_status) AND (desired_digest IS NULL) AND (desired_document IS NULL) AND ((desired_reason_code)::text = 'runtime_profile_required'::text)) OR ((desired_status = 'blocked'::public.runtime_configuration_state_status) AND (desired_reason_code IS NOT NULL)) OR ((desired_status = 'ready'::public.runtime_configuration_state_status) AND (desired_digest IS NOT NULL) AND (desired_document IS NOT NULL) AND (desired_reason_code IS NULL)))),
    CONSTRAINT ck_runtime_configuration_states_sequence CHECK (((desired_sequence >= 1) AND ((applied_sequence IS NULL) OR (applied_sequence >= 1))))
);


--
-- Name: runtime_connection_generation_cutovers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_connection_generation_cutovers (
    allocator_version smallint NOT NULL,
    cutover_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_runtime_connection_generation_cutovers_positive_version CHECK ((allocator_version > 0))
);


--
-- Name: runtime_connection_generation_cutovers_allocator_version_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.runtime_connection_generation_cutovers_allocator_version_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: runtime_connection_generation_cutovers_allocator_version_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.runtime_connection_generation_cutovers_allocator_version_seq OWNED BY public.runtime_connection_generation_cutovers.allocator_version;


--
-- Name: runtime_connection_generations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_connection_generations (
    connection_kind public.runtime_connection_authority_kind NOT NULL,
    subject_id character varying(32) NOT NULL,
    high_water_generation bigint NOT NULL,
    accepted_generation bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_runtime_connection_generations_accepted_within_high_water CHECK ((accepted_generation <= high_water_generation)),
    CONSTRAINT ck_runtime_connection_generations_non_negative CHECK (((high_water_generation >= 0) AND (accepted_generation >= 0)))
);


--
-- Name: runtime_infrastructure_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_infrastructure_profiles (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    profile_kind public.runtime_infrastructure_profile_kind NOT NULL,
    display_name character varying(120) NOT NULL,
    description text NOT NULL,
    lifecycle public.runtime_profile_lifecycle NOT NULL,
    contract_family character varying(120) NOT NULL,
    schema_version integer NOT NULL,
    spec jsonb NOT NULL,
    required_capabilities jsonb NOT NULL,
    version integer NOT NULL,
    digest character varying(64) NOT NULL,
    created_by_user_id character varying(32),
    updated_by_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    terminal_enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_runtime_infrastructure_profiles_version_positive CHECK ((version >= 1))
);


--
-- Name: runtime_provider_audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_audit_events (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    event_type public.runtime_provider_audit_event_type NOT NULL,
    actor_user_id character varying(32),
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_auth_binding_audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_auth_binding_audit_events (
    id character varying(32) NOT NULL,
    binding_id character varying(32) NOT NULL,
    event_type public.runtime_provider_binding_audit_event_type NOT NULL,
    actor_user_id character varying(32),
    previous_admin_version integer,
    new_admin_version integer,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_auth_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_auth_bindings (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    auth_method public.runtime_provider_auth_method NOT NULL,
    subject character varying(255) NOT NULL,
    state public.runtime_provider_binding_state NOT NULL,
    owner public.runtime_provider_binding_owner NOT NULL,
    bootstrap_declaration_id character varying(32),
    config jsonb,
    admin_version integer DEFAULT 1 NOT NULL,
    last_authenticated_at timestamp with time zone,
    last_connected_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoked_by_user_id character varying(32),
    revocation_reason character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_bootstrap_declarations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_bootstrap_declarations (
    id character varying(32) NOT NULL,
    source_id character varying(32) NOT NULL,
    provider_logical_id character varying(120) NOT NULL,
    kind public.runtime_provider_kind NOT NULL,
    provider_id character varying(32),
    declaration_key character varying(255) NOT NULL,
    source_revision character varying(255) NOT NULL,
    source_digest character varying(64) NOT NULL,
    state public.runtime_provider_bootstrap_declaration_state NOT NULL,
    creation_seeds jsonb,
    conflict_code character varying(120),
    conflict_message text,
    last_seen_at timestamp with time zone,
    withdrawn_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_bootstrap_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_bootstrap_sources (
    id character varying(32) NOT NULL,
    source_key character varying(255) NOT NULL,
    adapter_kind public.runtime_provider_bootstrap_adapter_kind NOT NULL,
    last_revision character varying(255),
    last_digest character varying(64),
    last_reconciled_at timestamp with time zone,
    error_code character varying(120),
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_config_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_config_revisions (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    revision integer NOT NULL,
    base_revision_id character varying(32),
    contract_revision_id character varying(32) NOT NULL,
    config jsonb NOT NULL,
    state public.runtime_provider_config_revision_state NOT NULL,
    validation_status public.runtime_provider_config_validation_status NOT NULL,
    encrypted_secrets text,
    secret_metadata jsonb NOT NULL,
    validation_request_id character varying(32),
    validation_code character varying(120),
    validation_message text,
    validation_metadata jsonb,
    impact jsonb,
    created_by_user_id character varying(32),
    activated_by_user_id character varying(32),
    activated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_connections (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    credential_id character varying(32),
    connection_id character varying(120) NOT NULL,
    generation bigint NOT NULL,
    status public.runtime_provider_connection_status NOT NULL,
    reported_provider_type character varying(120) NOT NULL,
    reported_protocol_version character varying(120) NOT NULL,
    connected_at timestamp with time zone NOT NULL,
    last_heartbeat_at timestamp with time zone NOT NULL,
    disconnected_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    binding_id character varying(32) NOT NULL,
    auth_method public.runtime_provider_auth_method NOT NULL,
    auth_subject character varying(255) NOT NULL,
    evidence_expires_at timestamp with time zone,
    operational_diagnostics jsonb,
    diagnostics_checked_at timestamp with time zone
);


--
-- Name: runtime_provider_contract_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_contract_revisions (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    digest character varying(64) NOT NULL,
    implementation_version character varying(120) NOT NULL,
    protocol_version character varying(120) NOT NULL,
    contract jsonb NOT NULL,
    compatibility jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_provider_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_credentials (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    verifier character varying(64) NOT NULL,
    state public.runtime_provider_credential_state NOT NULL,
    expires_at timestamp with time zone,
    issued_grant_id character varying(32) NOT NULL,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoked_by_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    binding_id character varying(32) NOT NULL
);


--
-- Name: runtime_provider_enrollment_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_enrollment_grants (
    id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    verifier character varying(64) NOT NULL,
    state public.runtime_provider_enrollment_grant_state NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    issued_by_user_id character varying(32),
    issued_by_source_id character varying(32),
    consumed_at timestamp with time zone,
    consumed_credential_id character varying(32),
    revoked_at timestamp with time zone,
    revoked_by_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    binding_id character varying(32) NOT NULL,
    CONSTRAINT ck_runtime_provider_enrollment_grants_issuer CHECK ((((issued_by_user_id IS NOT NULL) AND (issued_by_source_id IS NULL)) OR ((issued_by_user_id IS NULL) AND (issued_by_source_id IS NOT NULL))))
);


--
-- Name: runtime_provider_workspace_availability; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_provider_workspace_availability (
    provider_id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_providers (
    id character varying(32) NOT NULL,
    provider_id character varying(120) NOT NULL,
    scope public.runtime_provider_scope NOT NULL,
    kind public.runtime_provider_kind NOT NULL,
    display_name character varying(120) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    capabilities jsonb NOT NULL,
    config_schema jsonb,
    metadata jsonb,
    workspace_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    registration_method public.runtime_provider_registration_method DEFAULT 'admin'::public.runtime_provider_registration_method NOT NULL,
    lifecycle_state public.runtime_provider_lifecycle_state DEFAULT 'active'::public.runtime_provider_lifecycle_state NOT NULL,
    availability_mode public.runtime_provider_availability_mode DEFAULT 'platform_wide'::public.runtime_provider_availability_mode NOT NULL,
    admin_version integer DEFAULT 0 NOT NULL,
    active_config_revision_id character varying(32),
    current_contract_revision_id character varying(32),
    CONSTRAINT ck_runtime_providers_workspace_scope CHECK ((((scope = 'workspace'::public.runtime_provider_scope) AND (workspace_id IS NOT NULL)) OR ((scope = 'system'::public.runtime_provider_scope) AND (workspace_id IS NULL))))
);


--
-- Name: runtime_recreation_operation_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_recreation_operation_items (
    id character varying(32) NOT NULL,
    operation_id character varying(32) NOT NULL,
    runtime_id character varying(32) NOT NULL,
    status public.runtime_recreation_item_status NOT NULL,
    attempt integer NOT NULL,
    failure_code character varying(120),
    failure_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    dispatched_generation integer,
    expected_configuration_sequence bigint NOT NULL,
    expected_configuration_digest character varying(64) NOT NULL,
    expected_desired_generation bigint NOT NULL,
    CONSTRAINT ck_runtime_recreation_operation_items_attempt CHECK ((attempt >= 0)),
    CONSTRAINT ck_runtime_recreation_operation_items_expected_evidence CHECK (((expected_configuration_sequence >= 1) AND (expected_desired_generation >= 0)))
);


--
-- Name: runtime_recreation_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runtime_recreation_operations (
    id character varying(32) NOT NULL,
    target_kind public.runtime_recreation_target_kind NOT NULL,
    target_id character varying(120) NOT NULL,
    target_version character varying(120) NOT NULL,
    status public.runtime_recreation_operation_status NOT NULL,
    concurrency_limit integer NOT NULL,
    actor_user_id character varying(32),
    actor_workspace_user_id character varying(32),
    total_count integer NOT NULL,
    pending_count integer NOT NULL,
    running_count integer NOT NULL,
    succeeded_count integer NOT NULL,
    skipped_count integer NOT NULL,
    failed_count integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT ck_runtime_recreation_operations_actor_scope CHECK (((actor_user_id IS NULL) OR (actor_workspace_user_id IS NULL))),
    CONSTRAINT ck_runtime_recreation_operations_concurrency CHECK ((concurrency_limit >= 1)),
    CONSTRAINT ck_runtime_recreation_operations_counts CHECK (((total_count >= 0) AND (pending_count >= 0) AND (running_count >= 0) AND (succeeded_count >= 0) AND (skipped_count >= 0) AND (failed_count >= 0)))
);


--
-- Name: sandbox_checkpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sandbox_checkpoints (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    agent_runtime_id character varying(32) NOT NULL,
    object_key character varying(1024) NOT NULL,
    kind public.sandbox_checkpoint_kind NOT NULL,
    format public.sandbox_checkpoint_format NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    restored_at timestamp with time zone,
    invalidated_at timestamp with time zone,
    invalidation_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sandbox_runtime_leases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sandbox_runtime_leases (
    id character varying(32) NOT NULL,
    agent_runtime_id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    provider_id character varying(120) NOT NULL,
    provider_runtime_id character varying(160),
    allocation_generation bigint NOT NULL,
    state public.sandbox_runtime_lease_state NOT NULL,
    lease_owner character varying(120) NOT NULL,
    expires_at timestamp with time zone,
    last_observed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scheduled_task_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_task_states (
    task_key character varying(120) NOT NULL,
    latest_status public.scheduled_task_status DEFAULT 'idle'::public.scheduled_task_status NOT NULL,
    next_run_at timestamp with time zone NOT NULL,
    last_started_at timestamp with time zone,
    last_finished_at timestamp with time zone,
    last_succeeded_at timestamp with time zone,
    last_failed_at timestamp with time zone,
    failure_streak integer DEFAULT 0 NOT NULL,
    latest_error_code character varying(120),
    latest_error_message text,
    latest_result_summary jsonb,
    lease_owner character varying(120),
    leased_at timestamp with time zone,
    lease_until timestamp with time zone,
    manual_requested_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: scheduled_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_tasks (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    agent_id character varying(32) NOT NULL,
    session_id character varying(32) NOT NULL,
    title character varying(120) NOT NULL,
    objective text NOT NULL,
    schedule_type public.scheduled_task_schedule_type NOT NULL,
    next_eligible_at timestamp with time zone NOT NULL,
    binding_id character varying(32),
    scheduled_at timestamp with time zone,
    cron_expression character varying(100),
    timezone character varying(64),
    active_cycle_id character varying(32),
    active_scheduled_for timestamp with time zone,
    pending_scheduled_for timestamp with time zone,
    lease_owner character varying(120),
    lease_until timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_scheduled_tasks_active_cycle_fence CHECK ((((active_cycle_id IS NULL) AND (active_scheduled_for IS NULL)) OR ((active_cycle_id IS NOT NULL) AND (active_scheduled_for IS NOT NULL)))),
    CONSTRAINT ck_scheduled_tasks_pending_occurrence CHECK (((pending_scheduled_for IS NULL) OR ((schedule_type = 'cron'::public.scheduled_task_schedule_type) AND (active_cycle_id IS NOT NULL)))),
    CONSTRAINT ck_scheduled_tasks_schedule_shape CHECK ((((schedule_type = 'once'::public.scheduled_task_schedule_type) AND (scheduled_at IS NOT NULL) AND (cron_expression IS NULL) AND (timezone IS NULL)) OR ((schedule_type = 'cron'::public.scheduled_task_schedule_type) AND (scheduled_at IS NULL) AND (cron_expression IS NOT NULL) AND (timezone IS NOT NULL))))
);


--
-- Name: session_agent_context_git_worktrees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_agent_context_git_worktrees (
    session_agent_context_id character varying(32) NOT NULL,
    source_project_path text NOT NULL,
    starting_ref text NOT NULL,
    worktree_path text NOT NULL,
    branch_name text NOT NULL,
    branch_created_by public.session_git_worktree_branch_created_by NOT NULL,
    status public.session_git_worktree_status NOT NULL,
    created_by_session_agent_id character varying(32),
    created_by_agent_session_id character varying(32),
    action_execution_id character varying(32),
    session_agent_context_project_id character varying(32),
    base_commit character varying(64),
    failure_summary text,
    cleanup_summary text,
    ready_at timestamp with time zone,
    failed_at timestamp with time zone,
    cleaned_at timestamp with time zone,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_agent_context_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_agent_context_projects (
    session_agent_context_id character varying(32) NOT NULL,
    path text NOT NULL,
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_agent_contexts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_agent_contexts (
    agent_id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    root_session_agent_id character varying(32),
    agent_runtime_id character varying(32),
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    working_folder_path text,
    working_folder_cleanup_status public.session_working_folder_cleanup_status NOT NULL,
    working_folder_cleanup_summary text,
    working_folder_cleanup_completed_at timestamp with time zone,
    working_folder_binding_state public.session_working_folder_binding_state DEFAULT 'bound'::public.session_working_folder_binding_state NOT NULL,
    working_folder_invalidated_by_removal_id character varying(32),
    working_folder_invalidated_at timestamp with time zone,
    CONSTRAINT ck_session_agent_contexts_working_folder_binding CHECK ((((working_folder_binding_state = 'none'::public.session_working_folder_binding_state) AND (working_folder_path IS NULL) AND (agent_runtime_id IS NULL) AND (working_folder_invalidated_by_removal_id IS NULL) AND (working_folder_invalidated_at IS NULL)) OR ((working_folder_binding_state = 'pending'::public.session_working_folder_binding_state) AND (working_folder_path IS NULL) AND (agent_runtime_id IS NOT NULL) AND (working_folder_invalidated_by_removal_id IS NULL) AND (working_folder_invalidated_at IS NULL)) OR ((working_folder_binding_state = 'bound'::public.session_working_folder_binding_state) AND (working_folder_path IS NOT NULL) AND (agent_runtime_id IS NOT NULL) AND (working_folder_invalidated_by_removal_id IS NULL) AND (working_folder_invalidated_at IS NULL)) OR ((working_folder_binding_state = 'invalidated'::public.session_working_folder_binding_state) AND (agent_runtime_id IS NOT NULL) AND (working_folder_invalidated_by_removal_id IS NOT NULL) AND (working_folder_invalidated_at IS NOT NULL))))
);


--
-- Name: session_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_agents (
    context_id character varying(32) NOT NULL,
    root_session_agent_id character varying(32) NOT NULL,
    agent_session_id character varying(32) NOT NULL,
    kind public.session_agent_kind NOT NULL,
    name character varying(120) NOT NULL,
    path text NOT NULL,
    agent_type character varying(120) NOT NULL,
    parent_session_agent_id character varying(32),
    last_task_message text,
    parent_observed_run_index integer,
    parent_observed_event_id character varying(32),
    id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_message_at timestamp with time zone
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id character varying(32) NOT NULL,
    refresh_token character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    prev_refresh_token character varying(64),
    revoked_at timestamp with time zone,
    user_agent text,
    ip_address character varying(45),
    max_expires_at timestamp with time zone,
    refresh_token_created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    user_id character varying(32) NOT NULL
);


--
-- Name: signup_token_redemptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signup_token_redemptions (
    id character varying(32) NOT NULL,
    signup_token_id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    email character varying(255) NOT NULL,
    ip_address character varying(64),
    user_agent text,
    redeemed_at timestamp with time zone NOT NULL
);


--
-- Name: signup_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signup_tokens (
    id character varying(32) NOT NULL,
    token_hash character varying(64) NOT NULL,
    email character varying(255) NOT NULL,
    created_by_user_id character varying(32),
    delivery_method public.signup_token_delivery_method NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    max_uses integer NOT NULL,
    used_count integer NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_signup_tokens_max_uses_positive CHECK ((max_uses > 0)),
    CONSTRAINT ck_signup_tokens_used_count_range CHECK (((used_count >= 0) AND (used_count <= max_uses)))
);


--
-- Name: system_bootstrap_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_bootstrap_states (
    id integer NOT NULL,
    token_hash character varying(64) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    consumed_at timestamp with time zone,
    CONSTRAINT ck_system_bootstrap_states_singleton_id CHECK ((id = 1))
);


--
-- Name: system_bootstrap_states_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_bootstrap_states_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_bootstrap_states_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_bootstrap_states_id_seq OWNED BY public.system_bootstrap_states.id;


--
-- Name: system_data_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_data_migrations (
    name character varying(160) NOT NULL,
    outcome public.system_data_migration_outcome NOT NULL,
    metadata jsonb NOT NULL,
    completed_at timestamp with time zone NOT NULL
);


--
-- Name: system_file_lifecycle_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_file_lifecycle_settings (
    id smallint DEFAULT '1'::smallint NOT NULL,
    archived_session_retention_days integer DEFAULT 30,
    updated_by_user_id character varying(32),
    revision bigint DEFAULT '1'::bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_system_file_lifecycle_settings_retention_days CHECK (((archived_session_retention_days IS NULL) OR (archived_session_retention_days >= 0))),
    CONSTRAINT ck_system_file_lifecycle_settings_singleton_id CHECK ((id = 1))
);


--
-- Name: system_setting_audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_setting_audit_events (
    id character varying(32) NOT NULL,
    section public.system_setting_section NOT NULL,
    event_type public.system_setting_audit_event_type NOT NULL,
    source public.system_setting_audit_source NOT NULL,
    changed_fields jsonb NOT NULL,
    secret_actions jsonb NOT NULL,
    impact_confirmed boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    previous_version integer,
    new_version integer,
    actor_user_id character varying(32),
    validation_status public.system_setting_validation_status,
    candidate_id character varying(32),
    confirmation_action character varying(120),
    metadata jsonb
);


--
-- Name: system_setting_candidates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_setting_candidates (
    id character varying(32) NOT NULL,
    section public.system_setting_section NOT NULL,
    schema_version integer NOT NULL,
    base_version integer NOT NULL,
    config jsonb NOT NULL,
    validation_status public.system_setting_validation_status NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    encrypted_secrets text,
    secret_metadata jsonb NOT NULL,
    validated_generation character varying(64),
    validation_code character varying(120),
    validation_message text,
    action_hint text,
    validation_metadata jsonb,
    impact jsonb,
    created_by_user_id character varying(32)
);


--
-- Name: system_setting_health; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_setting_health (
    section public.system_setting_section NOT NULL,
    effective_generation character varying(64) NOT NULL,
    status public.system_setting_health_status NOT NULL,
    checked_at timestamp with time zone NOT NULL,
    code character varying(120),
    message text,
    action_hint text,
    metadata jsonb,
    checked_by_user_id character varying(32)
);


--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_settings (
    section public.system_setting_section NOT NULL,
    schema_version integer NOT NULL,
    version integer NOT NULL,
    config jsonb NOT NULL,
    encrypted_secrets text,
    secret_metadata jsonb NOT NULL,
    validation_status public.system_setting_validation_status,
    validated_generation character varying(64),
    validation_metadata jsonb,
    validated_at timestamp with time zone,
    updated_by_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: system_user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_user_roles (
    user_id character varying(32) NOT NULL,
    role public.system_user_role NOT NULL,
    granted_by_user_id character varying(32),
    granted_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: toolkit_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.toolkit_configs (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    toolkit_type character varying(100) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    config jsonb NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    slug character varying(100) DEFAULT ''::character varying NOT NULL,
    prompt text,
    encrypted_credentials text,
    revision bigint DEFAULT 1 NOT NULL,
    always_expose_tools boolean DEFAULT false NOT NULL,
    owner_agent_id character varying(32)
);


--
-- Name: toolkit_scopes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.toolkit_scopes (
    id character varying(32) NOT NULL,
    toolkit_id character varying(32) NOT NULL,
    scope_type public.toolkit_scope_type NOT NULL,
    scope_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: toolkit_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.toolkit_states (
    id character varying(32) NOT NULL,
    session_id character varying(32),
    toolkit_namespace character varying(100) NOT NULL,
    state_name character varying(100) NOT NULL,
    state_json jsonb NOT NULL,
    schema_version integer NOT NULL,
    version integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    agent_id character varying(32) NOT NULL
);


--
-- Name: user_emails; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_emails (
    id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    email character varying(255) NOT NULL,
    verified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id character varying(32) NOT NULL,
    primary_email_id character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    locale character varying(35) DEFAULT 'en-US'::character varying NOT NULL,
    access_disabled_at timestamp with time zone
);


--
-- Name: workspace_invitations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_invitations (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    email character varying(255) NOT NULL,
    role public.workspace_user_role NOT NULL,
    invited_by character varying(32) NOT NULL,
    status public.invitation_status DEFAULT 'pending'::public.invitation_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_join_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_join_requests (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    message text,
    status public.join_request_status DEFAULT 'pending'::public.join_request_status NOT NULL,
    last_notified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace_model_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_model_settings (
    workspace_id character varying(32) NOT NULL,
    default_model_selection jsonb,
    default_lightweight_model_selection jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    default_selectable_model_options jsonb,
    default_main_model_label character varying(80),
    default_lightweight_model_label character varying(80),
    CONSTRAINT ck_ws_model_settings_selectable_options_shape CHECK (((default_selectable_model_options IS NULL) OR (jsonb_typeof(default_selectable_model_options) = 'null'::text) OR ((jsonb_typeof(default_selectable_model_options) = 'array'::text) AND ((jsonb_array_length(default_selectable_model_options) >= 1) AND (jsonb_array_length(default_selectable_model_options) <= 10)))))
);


--
-- Name: workspace_runtime_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_runtime_profiles (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    provider_id character varying(32) NOT NULL,
    infrastructure_profile_id character varying(32) NOT NULL,
    display_name character varying(120) NOT NULL,
    description text NOT NULL,
    lifecycle public.runtime_profile_lifecycle NOT NULL,
    policy jsonb NOT NULL,
    version integer NOT NULL,
    digest character varying(64) NOT NULL,
    created_by_workspace_user_id character varying(32),
    updated_by_workspace_user_id character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    terminal_enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_workspace_runtime_profiles_version_positive CHECK ((version >= 1))
);


--
-- Name: workspace_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace_users (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    role public.workspace_user_role DEFAULT 'member'::public.workspace_user_role NOT NULL,
    user_id character varying(32) NOT NULL
);


--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspaces (
    id character varying(32) NOT NULL,
    name character varying(255) NOT NULL,
    handle character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    default_runtime_profile_id character varying(32),
    default_runtime_profile_version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_workspaces_default_runtime_profile_version_positive CHECK ((default_runtime_profile_version >= 1))
);


--
-- Name: xai_oauth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.xai_oauth_sessions (
    id character varying(32) NOT NULL,
    workspace_id character varying(32) NOT NULL,
    user_id character varying(32) NOT NULL,
    method public.xai_oauth_connection_method NOT NULL,
    encrypted_device_code text NOT NULL,
    user_code character varying(128) NOT NULL,
    verification_uri text NOT NULL,
    interval_seconds integer NOT NULL,
    status public.xai_oauth_session_status DEFAULT 'pending'::public.xai_oauth_session_status NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: runtime_connection_generation_cutovers allocator_version; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_connection_generation_cutovers ALTER COLUMN allocator_version SET DEFAULT nextval('public.runtime_connection_generation_cutovers_allocator_version_seq'::regclass);


--
-- Name: system_bootstrap_states id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_bootstrap_states ALTER COLUMN id SET DEFAULT nextval('public.system_bootstrap_states_id_seq'::regclass);


--
-- Name: action_execution_events action_execution_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_execution_events
    ADD CONSTRAINT action_execution_events_pkey PRIMARY KEY (id);


--
-- Name: action_executions action_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_executions
    ADD CONSTRAINT action_executions_pkey PRIMARY KEY (id);


--
-- Name: agent_admins agent_admins_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_admins
    ADD CONSTRAINT agent_admins_pkey PRIMARY KEY (id);


--
-- Name: agent_automatic_project_items agent_automatic_project_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_items
    ADD CONSTRAINT agent_automatic_project_items_pkey PRIMARY KEY (id);


--
-- Name: agent_automatic_project_settings agent_automatic_project_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_settings
    ADD CONSTRAINT agent_automatic_project_settings_pkey PRIMARY KEY (agent_id);


--
-- Name: agent_avatar_cleanup_jobs agent_avatar_cleanup_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_avatar_cleanup_jobs
    ADD CONSTRAINT agent_avatar_cleanup_jobs_pkey PRIMARY KEY (id);


--
-- Name: agent_decommission_jobs agent_decommission_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_decommission_jobs
    ADD CONSTRAINT agent_decommission_jobs_pkey PRIMARY KEY (id);


--
-- Name: agent_memories agent_memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memories
    ADD CONSTRAINT agent_memories_pkey PRIMARY KEY (id);


--
-- Name: agent_project_catalog_entries agent_project_catalog_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_catalog_entries
    ADD CONSTRAINT agent_project_catalog_entries_pkey PRIMARY KEY (id);


--
-- Name: agent_project_defaults agent_project_defaults_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_defaults
    ADD CONSTRAINT agent_project_defaults_pkey PRIMARY KEY (id);


--
-- Name: agent_project_presets agent_project_presets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_presets
    ADD CONSTRAINT agent_project_presets_pkey PRIMARY KEY (id);


--
-- Name: agent_run_input_events agent_run_input_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_input_events
    ADD CONSTRAINT agent_run_input_events_pkey PRIMARY KEY (agent_run_id, event_id);


--
-- Name: agent_runtime_add_receipts agent_runtime_add_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_add_receipts
    ADD CONSTRAINT agent_runtime_add_receipts_pkey PRIMARY KEY (id);


--
-- Name: agent_runtime_removal_operations agent_runtime_removal_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_removal_operations
    ADD CONSTRAINT agent_runtime_removal_operations_pkey PRIMARY KEY (id);


--
-- Name: agent_runtimes agent_runtimes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtimes
    ADD CONSTRAINT agent_runtimes_pkey PRIMARY KEY (id);


--
-- Name: agent_session_system_prompt_snapshots agent_session_system_prompt_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_session_system_prompt_snapshots
    ADD CONSTRAINT agent_session_system_prompt_snapshots_pkey PRIMARY KEY (session_id);


--
-- Name: agent_session_unread_runs agent_session_unread_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_session_unread_runs
    ADD CONSTRAINT agent_session_unread_runs_pkey PRIMARY KEY (session_id);


--
-- Name: agent_toolkits agent_toolkits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_toolkits
    ADD CONSTRAINT agent_toolkits_pkey PRIMARY KEY (id);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: archived_session_purge_jobs archived_session_purge_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_session_purge_jobs
    ADD CONSTRAINT archived_session_purge_jobs_pkey PRIMARY KEY (id);


--
-- Name: archived_session_purge_participant_executions archived_session_purge_participant_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_session_purge_participant_executions
    ADD CONSTRAINT archived_session_purge_participant_executions_pkey PRIMARY KEY (purge_job_id, participant_key);


--
-- Name: archived_session_retention_applications archived_session_retention_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_session_retention_applications
    ADD CONSTRAINT archived_session_retention_applications_pkey PRIMARY KEY (id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: chat_write_requests chat_write_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_write_requests
    ADD CONSTRAINT chat_write_requests_pkey PRIMARY KEY (id);


--
-- Name: chatgpt_oauth_sessions chatgpt_oauth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chatgpt_oauth_sessions
    ADD CONSTRAINT chatgpt_oauth_sessions_pkey PRIMARY KEY (id);


--
-- Name: email_verifications email_verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_verifications
    ADD CONSTRAINT email_verifications_pkey PRIMARY KEY (id);


--
-- Name: exchange_files exchange_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT exchange_files_pkey PRIMARY KEY (id);


--
-- Name: external_channel_access_grants external_channel_access_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_pkey PRIMARY KEY (id);


--
-- Name: external_channel_access_requests external_channel_access_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_pkey PRIMARY KEY (id);


--
-- Name: external_channel_agent_route_bot_policy_archive external_channel_agent_route_bot_policy_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_route_bot_policy_archive
    ADD CONSTRAINT external_channel_agent_route_bot_policy_archive_pkey PRIMARY KEY (route_id);


--
-- Name: external_channel_agent_routes external_channel_agent_routes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_routes
    ADD CONSTRAINT external_channel_agent_routes_pkey PRIMARY KEY (id);


--
-- Name: external_channel_app_claims external_channel_app_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_app_claims
    ADD CONSTRAINT external_channel_app_claims_pkey PRIMARY KEY (id);


--
-- Name: external_channel_bindings external_channel_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_pkey PRIMARY KEY (id);


--
-- Name: external_channel_blocks external_channel_blocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_blocks
    ADD CONSTRAINT external_channel_blocks_pkey PRIMARY KEY (id);


--
-- Name: external_channel_channel_defaults external_channel_channel_defaults_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_channel_defaults
    ADD CONSTRAINT external_channel_channel_defaults_pkey PRIMARY KEY (id);


--
-- Name: external_channel_connections external_channel_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_connections
    ADD CONSTRAINT external_channel_connections_pkey PRIMARY KEY (id);


--
-- Name: external_channel_conversation_positions external_channel_conversation_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_conversation_positions
    ADD CONSTRAINT external_channel_conversation_positions_pkey PRIMARY KEY (id);


--
-- Name: external_channel_ingress_items external_channel_ingress_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT external_channel_ingress_items_pkey PRIMARY KEY (id);


--
-- Name: external_channel_ingress_leases external_channel_ingress_leases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_leases
    ADD CONSTRAINT external_channel_ingress_leases_pkey PRIMARY KEY (id);


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_pkey PRIMARY KEY (id);


--
-- Name: external_channel_interactions external_channel_interactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_interactions
    ADD CONSTRAINT external_channel_interactions_pkey PRIMARY KEY (id);


--
-- Name: external_channel_participation_settings external_channel_participation_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_participation_settings
    ADD CONSTRAINT external_channel_participation_settings_pkey PRIMARY KEY (id);


--
-- Name: external_channel_principals external_channel_principals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_principals
    ADD CONSTRAINT external_channel_principals_pkey PRIMARY KEY (id);


--
-- Name: external_channel_resources external_channel_resources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_resources
    ADD CONSTRAINT external_channel_resources_pkey PRIMARY KEY (id);


--
-- Name: external_channel_setup_claims external_channel_setup_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT external_channel_setup_claims_pkey PRIMARY KEY (id);


--
-- Name: git_worktree_path_claims git_worktree_path_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_worktree_path_claims
    ADD CONSTRAINT git_worktree_path_claims_pkey PRIMARY KEY (id);


--
-- Name: github_user_installations github_user_installations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_user_installations
    ADD CONSTRAINT github_user_installations_pkey PRIMARY KEY (id);


--
-- Name: kimi_oauth_sessions kimi_oauth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kimi_oauth_sessions
    ADD CONSTRAINT kimi_oauth_sessions_pkey PRIMARY KEY (id);


--
-- Name: litellm_source_snapshots litellm_source_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.litellm_source_snapshots
    ADD CONSTRAINT litellm_source_snapshots_pkey PRIMARY KEY (id);


--
-- Name: llm_catalog_entries llm_catalog_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_entries
    ADD CONSTRAINT llm_catalog_entries_pkey PRIMARY KEY (id);


--
-- Name: llm_catalog_snapshots llm_catalog_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_snapshots
    ADD CONSTRAINT llm_catalog_snapshots_pkey PRIMARY KEY (id);


--
-- Name: llm_catalog_sync_attempts llm_catalog_sync_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_sync_attempts
    ADD CONSTRAINT llm_catalog_sync_attempts_pkey PRIMARY KEY (id);


--
-- Name: llm_catalogs llm_catalogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalogs
    ADD CONSTRAINT llm_catalogs_pkey PRIMARY KEY (id);


--
-- Name: llm_provider_integrations llm_provider_integrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_provider_integrations
    ADD CONSTRAINT llm_provider_integrations_pkey PRIMARY KEY (id);


--
-- Name: mcp_oauth_connections mcp_oauth_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_oauth_connections
    ADD CONSTRAINT mcp_oauth_connections_pkey PRIMARY KEY (id);


--
-- Name: model_files model_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_files
    ADD CONSTRAINT model_files_pkey PRIMARY KEY (id);


--
-- Name: owner_lifecycle_jobs owner_lifecycle_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owner_lifecycle_jobs
    ADD CONSTRAINT owner_lifecycle_jobs_pkey PRIMARY KEY (id);


--
-- Name: password_logins password_logins_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_logins
    ADD CONSTRAINT password_logins_pkey PRIMARY KEY (id);


--
-- Name: password_reset_token_redemptions password_reset_token_redemptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_token_redemptions
    ADD CONSTRAINT password_reset_token_redemptions_pkey PRIMARY KEY (id);


--
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- Name: agent_runs pk_agent_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT pk_agent_runs PRIMARY KEY (id);


--
-- Name: agent_sessions pk_agent_sessions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT pk_agent_sessions PRIMARY KEY (id);


--
-- Name: events pk_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT pk_events PRIMARY KEY (id);


--
-- Name: mailbox_items pk_mailbox_items; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mailbox_items
    ADD CONSTRAINT pk_mailbox_items PRIMARY KEY (id);


--
-- Name: runtime_configuration_reconcile_tasks runtime_configuration_reconcile_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_configuration_reconcile_tasks
    ADD CONSTRAINT runtime_configuration_reconcile_tasks_pkey PRIMARY KEY (id);


--
-- Name: runtime_configuration_states runtime_configuration_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_configuration_states
    ADD CONSTRAINT runtime_configuration_states_pkey PRIMARY KEY (runtime_id);


--
-- Name: runtime_connection_generation_cutovers runtime_connection_generation_cutovers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_connection_generation_cutovers
    ADD CONSTRAINT runtime_connection_generation_cutovers_pkey PRIMARY KEY (allocator_version);


--
-- Name: runtime_connection_generations runtime_connection_generations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_connection_generations
    ADD CONSTRAINT runtime_connection_generations_pkey PRIMARY KEY (connection_kind, subject_id);


--
-- Name: runtime_infrastructure_profiles runtime_infrastructure_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_infrastructure_profiles
    ADD CONSTRAINT runtime_infrastructure_profiles_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_audit_events runtime_provider_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_audit_events
    ADD CONSTRAINT runtime_provider_audit_events_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_auth_binding_audit_events runtime_provider_auth_binding_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_binding_audit_events
    ADD CONSTRAINT runtime_provider_auth_binding_audit_events_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_auth_bindings runtime_provider_auth_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_bindings
    ADD CONSTRAINT runtime_provider_auth_bindings_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_bootstrap_declarations runtime_provider_bootstrap_declarations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_declarations
    ADD CONSTRAINT runtime_provider_bootstrap_declarations_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_bootstrap_sources runtime_provider_bootstrap_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_sources
    ADD CONSTRAINT runtime_provider_bootstrap_sources_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_config_revisions runtime_provider_config_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT runtime_provider_config_revisions_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_connections runtime_provider_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_connections
    ADD CONSTRAINT runtime_provider_connections_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_contract_revisions runtime_provider_contract_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_contract_revisions
    ADD CONSTRAINT runtime_provider_contract_revisions_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_credentials runtime_provider_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_credentials
    ADD CONSTRAINT runtime_provider_credentials_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_enrollment_grants runtime_provider_enrollment_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_enrollment_grants
    ADD CONSTRAINT runtime_provider_enrollment_grants_pkey PRIMARY KEY (id);


--
-- Name: runtime_provider_workspace_availability runtime_provider_workspace_availability_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_workspace_availability
    ADD CONSTRAINT runtime_provider_workspace_availability_pkey PRIMARY KEY (provider_id, workspace_id);


--
-- Name: runtime_providers runtime_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_providers
    ADD CONSTRAINT runtime_providers_pkey PRIMARY KEY (id);


--
-- Name: runtime_recreation_operation_items runtime_recreation_operation_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operation_items
    ADD CONSTRAINT runtime_recreation_operation_items_pkey PRIMARY KEY (id);


--
-- Name: runtime_recreation_operations runtime_recreation_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operations
    ADD CONSTRAINT runtime_recreation_operations_pkey PRIMARY KEY (id);


--
-- Name: sandbox_checkpoints sandbox_checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_checkpoints
    ADD CONSTRAINT sandbox_checkpoints_pkey PRIMARY KEY (id);


--
-- Name: sandbox_runtime_leases sandbox_runtime_leases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_runtime_leases
    ADD CONSTRAINT sandbox_runtime_leases_pkey PRIMARY KEY (id);


--
-- Name: scheduled_task_states scheduled_task_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_task_states
    ADD CONSTRAINT scheduled_task_states_pkey PRIMARY KEY (task_key);


--
-- Name: scheduled_tasks scheduled_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks
    ADD CONSTRAINT scheduled_tasks_pkey PRIMARY KEY (id);


--
-- Name: session_agent_context_git_worktrees session_agent_context_git_worktrees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_git_worktrees
    ADD CONSTRAINT session_agent_context_git_worktrees_pkey PRIMARY KEY (id);


--
-- Name: session_agent_context_projects session_agent_context_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_projects
    ADD CONSTRAINT session_agent_context_projects_pkey PRIMARY KEY (id);


--
-- Name: session_agent_contexts session_agent_contexts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT session_agent_contexts_pkey PRIMARY KEY (id);


--
-- Name: session_agents session_agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT session_agents_pkey PRIMARY KEY (id);


--
-- Name: kubernetes_sandbox_snapshots session_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kubernetes_sandbox_snapshots
    ADD CONSTRAINT session_snapshots_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: signup_token_redemptions signup_token_redemptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signup_token_redemptions
    ADD CONSTRAINT signup_token_redemptions_pkey PRIMARY KEY (id);


--
-- Name: signup_tokens signup_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signup_tokens
    ADD CONSTRAINT signup_tokens_pkey PRIMARY KEY (id);


--
-- Name: system_bootstrap_states system_bootstrap_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_bootstrap_states
    ADD CONSTRAINT system_bootstrap_states_pkey PRIMARY KEY (id);


--
-- Name: system_data_migrations system_data_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_data_migrations
    ADD CONSTRAINT system_data_migrations_pkey PRIMARY KEY (name);


--
-- Name: system_file_lifecycle_settings system_file_lifecycle_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_file_lifecycle_settings
    ADD CONSTRAINT system_file_lifecycle_settings_pkey PRIMARY KEY (id);


--
-- Name: system_setting_audit_events system_setting_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_audit_events
    ADD CONSTRAINT system_setting_audit_events_pkey PRIMARY KEY (id);


--
-- Name: system_setting_candidates system_setting_candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_candidates
    ADD CONSTRAINT system_setting_candidates_pkey PRIMARY KEY (id);


--
-- Name: system_setting_health system_setting_health_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_health
    ADD CONSTRAINT system_setting_health_pkey PRIMARY KEY (section);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (section);


--
-- Name: system_user_roles system_user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_user_roles
    ADD CONSTRAINT system_user_roles_pkey PRIMARY KEY (user_id, role);


--
-- Name: toolkit_scopes toolkit_scopes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_scopes
    ADD CONSTRAINT toolkit_scopes_pkey PRIMARY KEY (id);


--
-- Name: toolkit_states toolkit_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_states
    ADD CONSTRAINT toolkit_states_pkey PRIMARY KEY (id);


--
-- Name: toolkit_configs toolkits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_configs
    ADD CONSTRAINT toolkits_pkey PRIMARY KEY (id);


--
-- Name: action_execution_events uq_action_execution_events_execution_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_execution_events
    ADD CONSTRAINT uq_action_execution_events_execution_sequence UNIQUE (action_execution_id, sequence);


--
-- Name: action_executions uq_action_executions_mailbox_item_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_executions
    ADD CONSTRAINT uq_action_executions_mailbox_item_id UNIQUE (mailbox_item_id);


--
-- Name: agent_admins uq_agent_admins_agent_workspace_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_admins
    ADD CONSTRAINT uq_agent_admins_agent_workspace_user UNIQUE (agent_id, workspace_user_id);


--
-- Name: agent_automatic_project_items uq_agent_automatic_project_items_agent_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_items
    ADD CONSTRAINT uq_agent_automatic_project_items_agent_path UNIQUE (agent_id, path);


--
-- Name: agent_automatic_project_items uq_agent_automatic_project_items_agent_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_items
    ADD CONSTRAINT uq_agent_automatic_project_items_agent_position UNIQUE (agent_id, "position");


--
-- Name: agent_decommission_jobs uq_agent_decommission_jobs_agent_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_decommission_jobs
    ADD CONSTRAINT uq_agent_decommission_jobs_agent_id UNIQUE (agent_id);


--
-- Name: agent_project_catalog_entries uq_agent_project_catalog_entries_agent_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_catalog_entries
    ADD CONSTRAINT uq_agent_project_catalog_entries_agent_path UNIQUE (agent_id, path);


--
-- Name: agent_project_defaults uq_agent_project_defaults_agent_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_defaults
    ADD CONSTRAINT uq_agent_project_defaults_agent_position UNIQUE (agent_id, "position");


--
-- Name: agent_project_presets uq_agent_project_presets_agent_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_presets
    ADD CONSTRAINT uq_agent_project_presets_agent_path UNIQUE (agent_id, path);


--
-- Name: agent_run_input_events uq_agent_run_input_events_run_input_order; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_input_events
    ADD CONSTRAINT uq_agent_run_input_events_run_input_order UNIQUE (agent_run_id, input_order);


--
-- Name: agent_runs uq_agent_runs_session_run_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT uq_agent_runs_session_run_index UNIQUE (session_id, run_index);


--
-- Name: agent_runtimes uq_agent_runtimes_agent_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtimes
    ADD CONSTRAINT uq_agent_runtimes_agent_id UNIQUE (agent_id);


--
-- Name: agent_runtimes uq_agent_runtimes_id_workspace_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtimes
    ADD CONSTRAINT uq_agent_runtimes_id_workspace_id UNIQUE (id, workspace_id);


--
-- Name: agent_session_unread_runs uq_agent_session_unread_runs_run_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_session_unread_runs
    ADD CONSTRAINT uq_agent_session_unread_runs_run_id UNIQUE (run_id);


--
-- Name: agent_sessions uq_agent_sessions_handle; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT uq_agent_sessions_handle UNIQUE (handle);


--
-- Name: agent_toolkits uq_agent_toolkits_agent_toolkit; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_toolkits
    ADD CONSTRAINT uq_agent_toolkits_agent_toolkit UNIQUE (agent_id, toolkit_id);


--
-- Name: archived_session_purge_jobs uq_archived_session_purge_jobs_root_session_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_session_purge_jobs
    ADD CONSTRAINT uq_archived_session_purge_jobs_root_session_id UNIQUE (root_session_id);


--
-- Name: artifacts uq_artifacts_storage_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT uq_artifacts_storage_key UNIQUE (storage_key);


--
-- Name: chat_write_requests uq_chat_write_requests_session_requester_client_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_write_requests
    ADD CONSTRAINT uq_chat_write_requests_session_requester_client_request UNIQUE (session_id, requester_user_id, client_request_id);


--
-- Name: exchange_files uq_exchange_files_object_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT uq_exchange_files_object_key UNIQUE (object_key);


--
-- Name: external_channel_access_requests uq_external_channel_access_requests_route_trigger_message; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT uq_external_channel_access_requests_route_trigger_message UNIQUE (route_id, trigger_provider_message_key);


--
-- Name: external_channel_agent_routes uq_external_channel_agent_routes_connection_agent; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_routes
    ADD CONSTRAINT uq_external_channel_agent_routes_connection_agent UNIQUE (connection_id, agent_id_snapshot);


--
-- Name: external_channel_agent_routes uq_external_channel_agent_routes_connection_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_routes
    ADD CONSTRAINT uq_external_channel_agent_routes_connection_id_id UNIQUE (connection_id, id);


--
-- Name: external_channel_app_claims uq_external_channel_app_claims_provider_app_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_app_claims
    ADD CONSTRAINT uq_external_channel_app_claims_provider_app_id UNIQUE (provider, provider_app_id);


--
-- Name: external_channel_blocks uq_external_channel_blocks_agent_principal; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_blocks
    ADD CONSTRAINT uq_external_channel_blocks_agent_principal UNIQUE (agent_id, principal_id);


--
-- Name: external_channel_connections uq_external_channel_connections_id_app_mode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_connections
    ADD CONSTRAINT uq_external_channel_connections_id_app_mode UNIQUE (id, app_mode);


--
-- Name: external_channel_conversation_positions uq_external_channel_conversation_positions_connection_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_conversation_positions
    ADD CONSTRAINT uq_external_channel_conversation_positions_connection_id_id UNIQUE (connection_id, id);


--
-- Name: external_channel_ingress_items uq_external_channel_ingress_items_active_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT uq_external_channel_ingress_items_active_identity UNIQUE (owner_id, deduplication_key);


--
-- Name: external_channel_ingress_items uq_external_channel_ingress_items_queue_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT uq_external_channel_ingress_items_queue_key UNIQUE (queue_key);


--
-- Name: external_channel_ingress_leases uq_external_channel_ingress_leases_connection_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_leases
    ADD CONSTRAINT uq_external_channel_ingress_leases_connection_id UNIQUE (connection_id);


--
-- Name: external_channel_ingress_owners uq_external_channel_ingress_owners_target_resource; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT uq_external_channel_ingress_owners_target_resource UNIQUE (target_resource_id);


--
-- Name: external_channel_interactions uq_external_channel_interactions_connection_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_interactions
    ADD CONSTRAINT uq_external_channel_interactions_connection_id_id UNIQUE (connection_id, id);


--
-- Name: external_channel_interactions uq_external_channel_interactions_connection_provider_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_interactions
    ADD CONSTRAINT uq_external_channel_interactions_connection_provider_key UNIQUE (connection_id, provider_interaction_key);


--
-- Name: external_channel_participation_settings uq_external_channel_participation_settings_connection_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_participation_settings
    ADD CONSTRAINT uq_external_channel_participation_settings_connection_id_id UNIQUE (connection_id, id);


--
-- Name: external_channel_principals uq_external_channel_principals_provider_tenant_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_principals
    ADD CONSTRAINT uq_external_channel_principals_provider_tenant_user UNIQUE (provider, provider_tenant_id, provider_user_id);


--
-- Name: external_channel_resources uq_external_channel_resources_connection_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_resources
    ADD CONSTRAINT uq_external_channel_resources_connection_id_id UNIQUE (connection_id, id);


--
-- Name: external_channel_resources uq_external_channel_resources_connection_type_provider_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_resources
    ADD CONSTRAINT uq_external_channel_resources_connection_type_provider_key UNIQUE (connection_id, resource_type, provider_resource_key);


--
-- Name: external_channel_setup_claims uq_external_channel_setup_claims_connection_id_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT uq_external_channel_setup_claims_connection_id_id UNIQUE (connection_id, id);


--
-- Name: git_worktree_path_claims uq_git_worktree_path_claims_agent_runtime_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_worktree_path_claims
    ADD CONSTRAINT uq_git_worktree_path_claims_agent_runtime_path UNIQUE (agent_runtime_id, worktree_path);


--
-- Name: litellm_source_snapshots uq_litellm_source_snapshots_source_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.litellm_source_snapshots
    ADD CONSTRAINT uq_litellm_source_snapshots_source_hash UNIQUE (source_hash);


--
-- Name: mcp_oauth_connections uq_mcp_oauth_connections_toolkit_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_oauth_connections
    ADD CONSTRAINT uq_mcp_oauth_connections_toolkit_id UNIQUE (toolkit_id);


--
-- Name: model_file_pins uq_model_file_pins_model_file_run; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_file_pins
    ADD CONSTRAINT uq_model_file_pins_model_file_run PRIMARY KEY (model_file_id, run_id);


--
-- Name: model_files uq_model_files_storage_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_files
    ADD CONSTRAINT uq_model_files_storage_key UNIQUE (storage_key);


--
-- Name: password_logins uq_password_logins_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_logins
    ADD CONSTRAINT uq_password_logins_user_id UNIQUE (user_id);


--
-- Name: password_reset_tokens uq_password_reset_tokens_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT uq_password_reset_tokens_token_hash UNIQUE (token_hash);


--
-- Name: runtime_configuration_reconcile_tasks uq_runtime_configuration_reconcile_tasks_source_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_configuration_reconcile_tasks
    ADD CONSTRAINT uq_runtime_configuration_reconcile_tasks_source_version UNIQUE (source_type, source_id, source_version);


--
-- Name: runtime_infrastructure_profiles uq_runtime_infrastructure_profiles_provider_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_infrastructure_profiles
    ADD CONSTRAINT uq_runtime_infrastructure_profiles_provider_id UNIQUE (provider_id, id);


--
-- Name: runtime_infrastructure_profiles uq_runtime_infrastructure_profiles_provider_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_infrastructure_profiles
    ADD CONSTRAINT uq_runtime_infrastructure_profiles_provider_name UNIQUE (provider_id, display_name);


--
-- Name: runtime_provider_bootstrap_declarations uq_runtime_provider_bootstrap_declarations_provider_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_declarations
    ADD CONSTRAINT uq_runtime_provider_bootstrap_declarations_provider_id UNIQUE (provider_id);


--
-- Name: runtime_provider_bootstrap_declarations uq_runtime_provider_bootstrap_declarations_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_declarations
    ADD CONSTRAINT uq_runtime_provider_bootstrap_declarations_source_key UNIQUE (source_id, declaration_key);


--
-- Name: runtime_provider_bootstrap_sources uq_runtime_provider_bootstrap_sources_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_sources
    ADD CONSTRAINT uq_runtime_provider_bootstrap_sources_source_key UNIQUE (source_key);


--
-- Name: runtime_provider_config_revisions uq_runtime_provider_config_revisions_provider_revision; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT uq_runtime_provider_config_revisions_provider_revision UNIQUE (provider_id, revision);


--
-- Name: runtime_provider_connections uq_runtime_provider_connections_connection_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_connections
    ADD CONSTRAINT uq_runtime_provider_connections_connection_id UNIQUE (connection_id);


--
-- Name: runtime_provider_connections uq_runtime_provider_connections_provider_generation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_connections
    ADD CONSTRAINT uq_runtime_provider_connections_provider_generation UNIQUE (provider_id, generation);


--
-- Name: runtime_providers uq_runtime_providers_provider_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_providers
    ADD CONSTRAINT uq_runtime_providers_provider_id UNIQUE (provider_id);


--
-- Name: runtime_recreation_operation_items uq_runtime_recreation_operation_items_operation_runtime; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operation_items
    ADD CONSTRAINT uq_runtime_recreation_operation_items_operation_runtime UNIQUE (operation_id, runtime_id);


--
-- Name: sandbox_checkpoints uq_sandbox_checkpoints_object_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_checkpoints
    ADD CONSTRAINT uq_sandbox_checkpoints_object_key UNIQUE (object_key);


--
-- Name: sandbox_runtime_leases uq_sandbox_runtime_leases_runtime_generation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_runtime_leases
    ADD CONSTRAINT uq_sandbox_runtime_leases_runtime_generation UNIQUE (agent_runtime_id, allocation_generation);


--
-- Name: session_agent_context_projects uq_session_agent_context_projects_context_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_projects
    ADD CONSTRAINT uq_session_agent_context_projects_context_path UNIQUE (session_agent_context_id, path);


--
-- Name: session_agent_contexts uq_session_agent_contexts_root_session_agent_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT uq_session_agent_contexts_root_session_agent_id UNIQUE (root_session_agent_id);


--
-- Name: session_agent_contexts uq_session_agent_contexts_working_folder_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT uq_session_agent_contexts_working_folder_path UNIQUE (working_folder_path);


--
-- Name: session_agents uq_session_agents_agent_session_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT uq_session_agents_agent_session_id UNIQUE (agent_session_id);


--
-- Name: session_agents uq_session_agents_parent_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT uq_session_agents_parent_name UNIQUE (parent_session_agent_id, name);


--
-- Name: session_agents uq_session_agents_root_path; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT uq_session_agents_root_path UNIQUE (root_session_agent_id, path);


--
-- Name: sessions uq_sessions_refresh_token; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT uq_sessions_refresh_token UNIQUE (refresh_token);


--
-- Name: signup_tokens uq_signup_tokens_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signup_tokens
    ADD CONSTRAINT uq_signup_tokens_token_hash UNIQUE (token_hash);


--
-- Name: system_setting_candidates uq_system_setting_candidates_section; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_candidates
    ADD CONSTRAINT uq_system_setting_candidates_section UNIQUE (section);


--
-- Name: toolkit_scopes uq_toolkit_scopes_toolkit_scope_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_scopes
    ADD CONSTRAINT uq_toolkit_scopes_toolkit_scope_id UNIQUE (toolkit_id, scope_type, scope_id);


--
-- Name: toolkit_states uq_toolkit_states_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_states
    ADD CONSTRAINT uq_toolkit_states_identity UNIQUE (agent_id, session_id, toolkit_namespace, state_name);


--
-- Name: user_emails uq_user_emails_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_emails
    ADD CONSTRAINT uq_user_emails_email UNIQUE (email);


--
-- Name: workspace_invitations uq_workspace_invitations_workspace_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT uq_workspace_invitations_workspace_email UNIQUE (workspace_id, email);


--
-- Name: workspace_join_requests uq_workspace_join_requests_workspace_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_join_requests
    ADD CONSTRAINT uq_workspace_join_requests_workspace_user UNIQUE (workspace_id, user_id);


--
-- Name: workspace_runtime_profiles uq_workspace_runtime_profiles_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_runtime_profiles
    ADD CONSTRAINT uq_workspace_runtime_profiles_name UNIQUE (workspace_id, display_name);


--
-- Name: workspace_users uq_workspace_users_workspace_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_users
    ADD CONSTRAINT uq_workspace_users_workspace_user UNIQUE (workspace_id, user_id);


--
-- Name: workspaces uq_workspaces_handle; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT uq_workspaces_handle UNIQUE (handle);


--
-- Name: user_emails user_emails_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_emails
    ADD CONSTRAINT user_emails_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: workspace_invitations workspace_invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_pkey PRIMARY KEY (id);


--
-- Name: workspace_join_requests workspace_join_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_join_requests
    ADD CONSTRAINT workspace_join_requests_pkey PRIMARY KEY (id);


--
-- Name: workspace_model_settings workspace_model_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_model_settings
    ADD CONSTRAINT workspace_model_settings_pkey PRIMARY KEY (workspace_id);


--
-- Name: workspace_runtime_profiles workspace_runtime_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_runtime_profiles
    ADD CONSTRAINT workspace_runtime_profiles_pkey PRIMARY KEY (id);


--
-- Name: workspace_users workspace_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_users
    ADD CONSTRAINT workspace_users_pkey PRIMARY KEY (id);


--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);


--
-- Name: xai_oauth_sessions xai_oauth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xai_oauth_sessions
    ADD CONSTRAINT xai_oauth_sessions_pkey PRIMARY KEY (id);


--
-- Name: ix_action_execution_events_action_execution_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_action_execution_events_action_execution_id ON public.action_execution_events USING btree (action_execution_id);


--
-- Name: ix_action_execution_events_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_action_execution_events_session_id ON public.action_execution_events USING btree (session_id);


--
-- Name: ix_action_executions_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_action_executions_session_id ON public.action_executions USING btree (session_id);


--
-- Name: ix_action_executions_session_id_mailbox_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_action_executions_session_id_mailbox_item_id ON public.action_executions USING btree (session_id, mailbox_item_id);


--
-- Name: ix_action_executions_session_id_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_action_executions_session_id_status ON public.action_executions USING btree (session_id, status);


--
-- Name: ix_agent_admins_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_admins_agent_id ON public.agent_admins USING btree (agent_id);


--
-- Name: ix_agent_admins_workspace_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_admins_workspace_user_id ON public.agent_admins USING btree (workspace_user_id);


--
-- Name: ix_agent_automatic_project_items_agent_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_automatic_project_items_agent_position ON public.agent_automatic_project_items USING btree (agent_id, "position");


--
-- Name: ix_agent_avatar_cleanup_jobs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_avatar_cleanup_jobs_agent_id ON public.agent_avatar_cleanup_jobs USING btree (agent_id);


--
-- Name: ix_agent_avatar_cleanup_jobs_next_attempt_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_avatar_cleanup_jobs_next_attempt_lease_until ON public.agent_avatar_cleanup_jobs USING btree (next_attempt_at, lease_until);


--
-- Name: ix_agent_decommission_jobs_status_next_attempt_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_decommission_jobs_status_next_attempt_at ON public.agent_decommission_jobs USING btree (status, next_attempt_at);


--
-- Name: ix_agent_memories_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_memories_agent_id ON public.agent_memories USING btree (agent_id) WHERE (user_id IS NULL);


--
-- Name: ix_agent_memories_agent_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_memories_agent_user ON public.agent_memories USING btree (agent_id, user_id) WHERE (user_id IS NOT NULL);


--
-- Name: ix_agent_project_catalog_entries_agent_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_project_catalog_entries_agent_updated ON public.agent_project_catalog_entries USING btree (agent_id, updated_at);


--
-- Name: ix_agent_project_defaults_agent_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_project_defaults_agent_position ON public.agent_project_defaults USING btree (agent_id, "position");


--
-- Name: ix_agent_project_presets_agent_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_project_presets_agent_updated ON public.agent_project_presets USING btree (agent_id, updated_at);


--
-- Name: ix_agent_run_input_events_event_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_input_events_event_run ON public.agent_run_input_events USING btree (event_id, agent_run_id);


--
-- Name: ix_agent_run_input_events_run_input_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_run_input_events_run_input_order ON public.agent_run_input_events USING btree (agent_run_id, input_order);


--
-- Name: ix_agent_runs_parent_agent_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_parent_agent_run_id ON public.agent_runs USING btree (parent_agent_run_id);


--
-- Name: ix_agent_runs_phase; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_phase ON public.agent_runs USING btree (phase);


--
-- Name: ix_agent_runs_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_session_id ON public.agent_runs USING btree (session_id);


--
-- Name: ix_agent_runs_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_session_status ON public.agent_runs USING btree (session_id, status);


--
-- Name: ix_agent_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_status ON public.agent_runs USING btree (status);


--
-- Name: ix_agent_runtime_add_receipts_agent_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_add_receipts_agent_created_at ON public.agent_runtime_add_receipts USING btree (agent_id, created_at);


--
-- Name: ix_agent_runtime_removal_operations_agent_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_removal_operations_agent_created_at ON public.agent_runtime_removal_operations USING btree (agent_id, created_at);


--
-- Name: ix_agent_runtime_removal_operations_status_next_attempt_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtime_removal_operations_status_next_attempt_at ON public.agent_runtime_removal_operations USING btree (status, next_attempt_at);


--
-- Name: ix_agent_runtimes_desired_observed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_desired_observed ON public.agent_runtimes USING btree (desired_state, provider_observed_state);


--
-- Name: ix_agent_runtimes_lifecycle_dispatch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_lifecycle_dispatch ON public.agent_runtimes USING btree (desired_generation, last_lifecycle_dispatch_generation);


--
-- Name: ix_agent_runtimes_provider_connection_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_provider_connection_state ON public.agent_runtimes USING btree (provider_connection_state);


--
-- Name: ix_agent_runtimes_provider_observe_requested_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_provider_observe_requested_at ON public.agent_runtimes USING btree (provider_observe_requested_at);


--
-- Name: ix_agent_runtimes_runner_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_runner_state ON public.agent_runtimes USING btree (runner_state);


--
-- Name: ix_agent_runtimes_runtime_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_runtime_provider_id ON public.agent_runtimes USING btree (runtime_provider_id);


--
-- Name: ix_agent_runtimes_runtime_provider_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_runtime_provider_resource_id ON public.agent_runtimes USING btree (runtime_provider_resource_id);


--
-- Name: ix_agent_runtimes_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runtimes_workspace_id ON public.agent_runtimes USING btree (workspace_id);


--
-- Name: ix_agent_sessions_active_auto_archive; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_active_auto_archive ON public.agent_sessions USING btree (last_activity_at, agent_id) WHERE ((status = 'active'::public.agent_session_status) AND (session_kind = 'root'::public.agent_session_kind) AND (pinned = false));


--
-- Name: ix_agent_sessions_agent_active_last_user_input; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_agent_active_last_user_input ON public.agent_sessions USING btree (agent_id, primary_kind, last_user_input_at) WHERE (status = 'active'::public.agent_session_status);


--
-- Name: ix_agent_sessions_agent_associated_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_agent_associated_user_status ON public.agent_sessions USING btree (agent_id, associated_user_id, status);


--
-- Name: ix_agent_sessions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_agent_id ON public.agent_sessions USING btree (agent_id);


--
-- Name: ix_agent_sessions_archived_purge_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_archived_purge_after ON public.agent_sessions USING btree (purge_after) WHERE ((status = 'archived'::public.agent_session_status) AND (session_kind = 'root'::public.agent_session_kind) AND (purge_after IS NOT NULL));


--
-- Name: ix_agent_sessions_associated_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_associated_user_id ON public.agent_sessions USING btree (associated_user_id);


--
-- Name: ix_agent_sessions_model_file_gc_cursor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_model_file_gc_cursor ON public.agent_sessions USING btree (model_file_gc_cursor_event_id NULLS FIRST, model_input_head_event_id) WHERE (model_input_head_event_id IS NOT NULL);


--
-- Name: ix_agent_sessions_model_input_head_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_model_input_head_event_id ON public.agent_sessions USING btree (model_input_head_event_id);


--
-- Name: ix_agent_sessions_pending_command; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_pending_command ON public.agent_sessions USING btree (pending_command_created_at) WHERE (pending_command_id IS NOT NULL);


--
-- Name: ix_agent_sessions_run_state_running; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_run_state_running ON public.agent_sessions USING btree (run_heartbeat_at) WHERE (run_state = 'running'::public.agent_session_run_state);


--
-- Name: ix_agent_sessions_session_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_session_kind ON public.agent_sessions USING btree (session_kind);


--
-- Name: ix_agent_sessions_stop_requested_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_stop_requested_at ON public.agent_sessions USING btree (stop_requested_at) WHERE (stop_requested_at IS NOT NULL);


--
-- Name: ix_agent_sessions_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_sessions_workspace_id ON public.agent_sessions USING btree (workspace_id);


--
-- Name: ix_agent_toolkits_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_toolkits_agent_id ON public.agent_toolkits USING btree (agent_id);


--
-- Name: ix_agents_runtime_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_runtime_profile_id ON public.agents USING btree (runtime_profile_id);


--
-- Name: ix_agents_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_workspace_id ON public.agents USING btree (workspace_id);


--
-- Name: ix_archived_purge_part_exec_job_phase; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_archived_purge_part_exec_job_phase ON public.archived_session_purge_participant_executions USING btree (purge_job_id, phase);


--
-- Name: ix_archived_session_purge_jobs_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_archived_session_purge_jobs_lease_until ON public.archived_session_purge_jobs USING btree (lease_until);


--
-- Name: ix_archived_session_purge_jobs_status_eligible_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_archived_session_purge_jobs_status_eligible_at ON public.archived_session_purge_jobs USING btree (status, eligible_at);


--
-- Name: ix_archived_session_retention_applications_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_archived_session_retention_applications_lease_until ON public.archived_session_retention_applications USING btree (lease_until);


--
-- Name: ix_archived_session_retention_applications_status_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_archived_session_retention_applications_status_created_at ON public.archived_session_retention_applications USING btree (status, created_at);


--
-- Name: ix_artifacts_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_session_status ON public.artifacts USING btree (session_id, status);


--
-- Name: ix_artifacts_status_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_status_expires_at ON public.artifacts USING btree (status, expires_at);


--
-- Name: ix_artifacts_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_artifacts_workspace_id ON public.artifacts USING btree (workspace_id);


--
-- Name: ix_chat_write_requests_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chat_write_requests_session_id ON public.chat_write_requests USING btree (session_id);


--
-- Name: ix_chatgpt_oauth_sessions_state; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_chatgpt_oauth_sessions_state ON public.chatgpt_oauth_sessions USING btree (state);


--
-- Name: ix_chatgpt_oauth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chatgpt_oauth_sessions_user_id ON public.chatgpt_oauth_sessions USING btree (user_id);


--
-- Name: ix_chatgpt_oauth_sessions_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_chatgpt_oauth_sessions_workspace_id ON public.chatgpt_oauth_sessions USING btree (workspace_id);


--
-- Name: ix_events_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_session_created ON public.events USING btree (session_id, id);


--
-- Name: ix_events_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_session_id ON public.events USING btree (session_id);


--
-- Name: ix_exchange_files_origin_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_files_origin_type ON public.exchange_files USING btree (origin_type);


--
-- Name: ix_exchange_files_preview_thumbnail_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_files_preview_thumbnail_file_id ON public.exchange_files USING btree (preview_thumbnail_file_id);


--
-- Name: ix_exchange_files_retention_root_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_files_retention_root_status ON public.exchange_files USING btree (retention_root_session_id, status, id) WHERE (retention_root_session_id IS NOT NULL);


--
-- Name: ix_exchange_files_status_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_files_status_expires_at ON public.exchange_files USING btree (status, expires_at);


--
-- Name: ix_exchange_files_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_files_workspace_id ON public.exchange_files USING btree (workspace_id);


--
-- Name: ix_external_channel_access_grants_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_access_grants_agent_id ON public.external_channel_access_grants USING btree (agent_id);


--
-- Name: ix_external_channel_access_grants_agent_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_access_grants_agent_session_id ON public.external_channel_access_grants USING btree (agent_session_id);


--
-- Name: ix_external_channel_access_requests_agent_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_access_requests_agent_session_id ON public.external_channel_access_requests USING btree (agent_session_id);


--
-- Name: ix_external_channel_access_requests_setup_claim_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_access_requests_setup_claim_id ON public.external_channel_access_requests USING btree (setup_claim_id);


--
-- Name: ix_external_channel_access_requests_status_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_access_requests_status_created_at ON public.external_channel_access_requests USING btree (status, created_at);


--
-- Name: ix_external_channel_agent_routes_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_agent_routes_agent_id ON public.external_channel_agent_routes USING btree (agent_id);


--
-- Name: ix_external_channel_agent_routes_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_agent_routes_connection_id ON public.external_channel_agent_routes USING btree (connection_id);


--
-- Name: ix_external_channel_app_claims_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_app_claims_connection_id ON public.external_channel_app_claims USING btree (connection_id);


--
-- Name: ix_external_channel_bindings_agent_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_bindings_agent_session_id ON public.external_channel_bindings USING btree (agent_session_id);


--
-- Name: ix_external_channel_bindings_route_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_bindings_route_id ON public.external_channel_bindings USING btree (route_id);


--
-- Name: ix_external_channel_channel_defaults_route_id_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_channel_defaults_route_id_status ON public.external_channel_channel_defaults USING btree (route_id, status);


--
-- Name: ix_external_channel_connections_slack_presence_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_connections_slack_presence_lease_until ON public.external_channel_connections USING btree (slack_presence_lease_until);


--
-- Name: ix_external_channel_connections_socket_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_connections_socket_lease_until ON public.external_channel_connections USING btree (socket_lease_until);


--
-- Name: ix_external_channel_connections_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_connections_status ON public.external_channel_connections USING btree (status);


--
-- Name: ix_external_channel_connections_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_connections_workspace_id ON public.external_channel_connections USING btree (workspace_id);


--
-- Name: ix_external_channel_ingress_items_owner_due_queue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_ingress_items_owner_due_queue ON public.external_channel_ingress_items USING btree (owner_id, state, next_attempt_at, queue_key);


--
-- Name: ix_external_channel_ingress_items_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_ingress_items_position ON public.external_channel_ingress_items USING btree (conversation_position_id, trigger_position);


--
-- Name: ix_external_channel_ingress_leases_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_ingress_leases_lease_until ON public.external_channel_ingress_leases USING btree (lease_until);


--
-- Name: ix_external_channel_ingress_owners_recovery; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_ingress_owners_recovery ON public.external_channel_ingress_owners USING btree (preparation_next_attempt_at, lease_expires_at, updated_at);


--
-- Name: ix_external_channel_interactions_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_interactions_expires_at ON public.external_channel_interactions USING btree (expires_at);


--
-- Name: ix_external_channel_interactions_setup_claim_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_interactions_setup_claim_id ON public.external_channel_interactions USING btree (setup_claim_id);


--
-- Name: ix_external_channel_participation_settings_route_id_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_participation_settings_route_id_status ON public.external_channel_participation_settings USING btree (route_id, status);


--
-- Name: ix_external_channel_resources_connection_id_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_resources_connection_id_status ON public.external_channel_resources USING btree (connection_id, status);


--
-- Name: ix_external_channel_resources_latest_activity_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_resources_latest_activity_at ON public.external_channel_resources USING btree (latest_activity_at);


--
-- Name: ix_external_channel_setup_claims_route_id_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_setup_claims_route_id_status ON public.external_channel_setup_claims USING btree (route_id, status);


--
-- Name: ix_external_channel_setup_claims_status_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_external_channel_setup_claims_status_expires_at ON public.external_channel_setup_claims USING btree (status, expires_at);


--
-- Name: ix_git_worktree_path_claims_action_execution_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_worktree_path_claims_action_execution_id ON public.git_worktree_path_claims USING btree (action_execution_id);


--
-- Name: ix_git_worktree_path_claims_agent_runtime_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_worktree_path_claims_agent_runtime_id ON public.git_worktree_path_claims USING btree (agent_runtime_id);


--
-- Name: ix_git_worktree_path_claims_root_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_git_worktree_path_claims_root_session_id ON public.git_worktree_path_claims USING btree (root_session_id);


--
-- Name: ix_github_user_installations_platform_app_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_github_user_installations_platform_app_id ON public.github_user_installations USING btree (platform_app_id);


--
-- Name: ix_github_user_installations_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_github_user_installations_user_id ON public.github_user_installations USING btree (user_id);


--
-- Name: ix_kimi_oauth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kimi_oauth_sessions_user_id ON public.kimi_oauth_sessions USING btree (user_id);


--
-- Name: ix_kimi_oauth_sessions_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kimi_oauth_sessions_workspace_id ON public.kimi_oauth_sessions USING btree (workspace_id);


--
-- Name: ix_kubernetes_sandbox_snapshots_agent_runtime_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kubernetes_sandbox_snapshots_agent_runtime_id_created_at ON public.kubernetes_sandbox_snapshots USING btree (agent_runtime_id, created_at DESC);


--
-- Name: ix_llm_catalog_entries_catalog_display; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_catalog_entries_catalog_display ON public.llm_catalog_entries USING btree (catalog_id, display_name);


--
-- Name: ix_llm_catalog_entries_catalog_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_catalog_entries_catalog_model ON public.llm_catalog_entries USING btree (catalog_id, provider_model_identifier);


--
-- Name: ix_llm_catalog_entries_snapshot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_catalog_entries_snapshot_id ON public.llm_catalog_entries USING btree (snapshot_id);


--
-- Name: ix_llm_catalog_snapshots_catalog_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_catalog_snapshots_catalog_id ON public.llm_catalog_snapshots USING btree (catalog_id);


--
-- Name: ix_llm_catalog_sync_attempts_catalog_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_catalog_sync_attempts_catalog_id ON public.llm_catalog_sync_attempts USING btree (catalog_id);


--
-- Name: ix_llm_catalogs_provider_integration_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_catalogs_provider_integration_id ON public.llm_catalogs USING btree (provider_integration_id);


--
-- Name: ix_llm_provider_integrations_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_provider_integrations_workspace_id ON public.llm_provider_integrations USING btree (workspace_id);


--
-- Name: ix_mailbox_items_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mailbox_items_kind ON public.mailbox_items USING btree (kind);


--
-- Name: ix_mailbox_items_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mailbox_items_session_id ON public.mailbox_items USING btree (session_id);


--
-- Name: ix_mailbox_items_session_id_scheduling_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mailbox_items_session_id_scheduling_mode ON public.mailbox_items USING btree (session_id, scheduling_mode);


--
-- Name: ix_mailbox_items_session_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mailbox_items_session_order ON public.mailbox_items USING btree (session_id, order_group, order_sequence, id);


--
-- Name: ix_mcp_oauth_connections_toolkit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mcp_oauth_connections_toolkit_id ON public.mcp_oauth_connections USING btree (toolkit_id);


--
-- Name: ix_model_file_pins_model_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_file_pins_model_file_id ON public.model_file_pins USING btree (model_file_id);


--
-- Name: ix_model_file_pins_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_file_pins_run_id ON public.model_file_pins USING btree (run_id);


--
-- Name: ix_model_files_session_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_files_session_status ON public.model_files USING btree (session_id, status);


--
-- Name: ix_model_files_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_files_workspace_id ON public.model_files USING btree (workspace_id);


--
-- Name: ix_owner_lifecycle_jobs_status_next_attempt_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_owner_lifecycle_jobs_status_next_attempt_at ON public.owner_lifecycle_jobs USING btree (status, next_attempt_at);


--
-- Name: ix_password_reset_token_redemptions_password_reset_token_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_token_redemptions_password_reset_token_id ON public.password_reset_token_redemptions USING btree (password_reset_token_id);


--
-- Name: ix_password_reset_token_redemptions_redeemed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_token_redemptions_redeemed_at ON public.password_reset_token_redemptions USING btree (redeemed_at);


--
-- Name: ix_password_reset_token_redemptions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_token_redemptions_user_id ON public.password_reset_token_redemptions USING btree (user_id);


--
-- Name: ix_password_reset_tokens_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_created_by_user_id ON public.password_reset_tokens USING btree (created_by_user_id);


--
-- Name: ix_password_reset_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_expires_at ON public.password_reset_tokens USING btree (expires_at);


--
-- Name: ix_password_reset_tokens_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_revoked_at ON public.password_reset_tokens USING btree (revoked_at);


--
-- Name: ix_password_reset_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_user_id ON public.password_reset_tokens USING btree (user_id);


--
-- Name: ix_runtime_configuration_reconcile_tasks_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_configuration_reconcile_tasks_source ON public.runtime_configuration_reconcile_tasks USING btree (source_type, source_id);


--
-- Name: ix_runtime_configuration_reconcile_tasks_status_available; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_configuration_reconcile_tasks_status_available ON public.runtime_configuration_reconcile_tasks USING btree (status, available_at);


--
-- Name: ix_runtime_infrastructure_profiles_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_infrastructure_profiles_kind ON public.runtime_infrastructure_profiles USING btree (profile_kind);


--
-- Name: ix_runtime_infrastructure_profiles_provider_lifecycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_infrastructure_profiles_provider_lifecycle ON public.runtime_infrastructure_profiles USING btree (provider_id, lifecycle);


--
-- Name: ix_runtime_provider_audit_events_provider_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_audit_events_provider_created ON public.runtime_provider_audit_events USING btree (provider_id, created_at);


--
-- Name: ix_runtime_provider_auth_binding_audit_events_binding_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_auth_binding_audit_events_binding_created ON public.runtime_provider_auth_binding_audit_events USING btree (binding_id, created_at);


--
-- Name: ix_runtime_provider_auth_bindings_method_subject_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_auth_bindings_method_subject_state ON public.runtime_provider_auth_bindings USING btree (auth_method, subject, state);


--
-- Name: ix_runtime_provider_auth_bindings_provider_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_auth_bindings_provider_state ON public.runtime_provider_auth_bindings USING btree (provider_id, state);


--
-- Name: ix_runtime_provider_bootstrap_sources_adapter_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_bootstrap_sources_adapter_kind ON public.runtime_provider_bootstrap_sources USING btree (adapter_kind);


--
-- Name: ix_runtime_provider_config_revisions_provider_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_config_revisions_provider_state ON public.runtime_provider_config_revisions USING btree (provider_id, state);


--
-- Name: ix_runtime_provider_config_revisions_validation_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_config_revisions_validation_request ON public.runtime_provider_config_revisions USING btree (validation_request_id);


--
-- Name: ix_runtime_provider_connections_binding_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_connections_binding_status ON public.runtime_provider_connections USING btree (binding_id, status);


--
-- Name: ix_runtime_provider_connections_credential_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_connections_credential_status ON public.runtime_provider_connections USING btree (credential_id, status);


--
-- Name: ix_runtime_provider_connections_provider_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_connections_provider_status ON public.runtime_provider_connections USING btree (provider_id, status);


--
-- Name: ix_runtime_provider_contract_revisions_provider_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_contract_revisions_provider_created ON public.runtime_provider_contract_revisions USING btree (provider_id, created_at);


--
-- Name: ix_runtime_provider_credentials_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_credentials_expires_at ON public.runtime_provider_credentials USING btree (expires_at);


--
-- Name: ix_runtime_provider_credentials_provider_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_credentials_provider_state ON public.runtime_provider_credentials USING btree (provider_id, state);


--
-- Name: ix_runtime_provider_enrollment_grants_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_enrollment_grants_expires_at ON public.runtime_provider_enrollment_grants USING btree (expires_at);


--
-- Name: ix_runtime_provider_enrollment_grants_provider_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_enrollment_grants_provider_state ON public.runtime_provider_enrollment_grants USING btree (provider_id, state);


--
-- Name: ix_runtime_provider_workspace_availability_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_provider_workspace_availability_workspace_id ON public.runtime_provider_workspace_availability USING btree (workspace_id);


--
-- Name: ix_runtime_providers_enabled_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_providers_enabled_scope ON public.runtime_providers USING btree (enabled, scope);


--
-- Name: ix_runtime_providers_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_providers_kind ON public.runtime_providers USING btree (kind);


--
-- Name: ix_runtime_providers_lifecycle_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_providers_lifecycle_enabled ON public.runtime_providers USING btree (lifecycle_state, enabled);


--
-- Name: ix_runtime_providers_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_providers_workspace_id ON public.runtime_providers USING btree (workspace_id);


--
-- Name: ix_runtime_recreation_operation_items_operation_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_recreation_operation_items_operation_status ON public.runtime_recreation_operation_items USING btree (operation_id, status);


--
-- Name: ix_runtime_recreation_operations_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_recreation_operations_status ON public.runtime_recreation_operations USING btree (status);


--
-- Name: ix_runtime_recreation_operations_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runtime_recreation_operations_target ON public.runtime_recreation_operations USING btree (target_kind, target_id);


--
-- Name: ix_sandbox_checkpoints_agent_runtime_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sandbox_checkpoints_agent_runtime_id_created_at ON public.sandbox_checkpoints USING btree (agent_runtime_id, created_at DESC);


--
-- Name: ix_sandbox_checkpoints_agent_runtime_id_invalidated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sandbox_checkpoints_agent_runtime_id_invalidated_at ON public.sandbox_checkpoints USING btree (agent_runtime_id, invalidated_at);


--
-- Name: ix_sandbox_checkpoints_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sandbox_checkpoints_workspace_id ON public.sandbox_checkpoints USING btree (workspace_id);


--
-- Name: ix_sandbox_runtime_leases_active_runtime; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_sandbox_runtime_leases_active_runtime ON public.sandbox_runtime_leases USING btree (agent_runtime_id) WHERE (state = ANY (ARRAY['allocating'::public.sandbox_runtime_lease_state, 'starting'::public.sandbox_runtime_lease_state, 'running'::public.sandbox_runtime_lease_state, 'hibernating'::public.sandbox_runtime_lease_state, 'deleting'::public.sandbox_runtime_lease_state]));


--
-- Name: ix_sandbox_runtime_leases_provider_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sandbox_runtime_leases_provider_state ON public.sandbox_runtime_leases USING btree (provider_id, state);


--
-- Name: ix_sandbox_runtime_leases_stale; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sandbox_runtime_leases_stale ON public.sandbox_runtime_leases USING btree (state, expires_at) WHERE (expires_at IS NOT NULL);


--
-- Name: ix_sandbox_runtime_leases_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sandbox_runtime_leases_workspace_id ON public.sandbox_runtime_leases USING btree (workspace_id);


--
-- Name: ix_scheduled_task_states_lease_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_task_states_lease_until ON public.scheduled_task_states USING btree (lease_until);


--
-- Name: ix_scheduled_task_states_next_run_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_task_states_next_run_at ON public.scheduled_task_states USING btree (next_run_at);


--
-- Name: ix_scheduled_tasks_active_cycle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_tasks_active_cycle_id ON public.scheduled_tasks USING btree (active_cycle_id);


--
-- Name: ix_scheduled_tasks_binding_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_tasks_binding_id ON public.scheduled_tasks USING btree (binding_id);


--
-- Name: ix_scheduled_tasks_next_eligible_at_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_tasks_next_eligible_at_id ON public.scheduled_tasks USING btree (next_eligible_at, id);


--
-- Name: ix_scheduled_tasks_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheduled_tasks_session_id ON public.scheduled_tasks USING btree (session_id);


--
-- Name: ix_session_agent_context_git_worktrees_action_execution_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_action_execution_id ON public.session_agent_context_git_worktrees USING btree (action_execution_id);


--
-- Name: ix_session_agent_context_git_worktrees_branch_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_branch_name ON public.session_agent_context_git_worktrees USING btree (branch_name);


--
-- Name: ix_session_agent_context_git_worktrees_context_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_context_id ON public.session_agent_context_git_worktrees USING btree (session_agent_context_id);


--
-- Name: ix_session_agent_context_git_worktrees_context_id_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_context_id_status ON public.session_agent_context_git_worktrees USING btree (session_agent_context_id, status);


--
-- Name: ix_session_agent_context_git_worktrees_context_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_context_project_id ON public.session_agent_context_git_worktrees USING btree (session_agent_context_project_id);


--
-- Name: ix_session_agent_context_git_worktrees_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_status ON public.session_agent_context_git_worktrees USING btree (status);


--
-- Name: ix_session_agent_context_git_worktrees_worktree_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_git_worktrees_worktree_path ON public.session_agent_context_git_worktrees USING btree (worktree_path);


--
-- Name: ix_session_agent_context_projects_context_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_context_projects_context_id ON public.session_agent_context_projects USING btree (session_agent_context_id);


--
-- Name: ix_session_agent_contexts_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_contexts_agent_id ON public.session_agent_contexts USING btree (agent_id);


--
-- Name: ix_session_agent_contexts_agent_runtime_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_contexts_agent_runtime_id ON public.session_agent_contexts USING btree (agent_runtime_id);


--
-- Name: ix_session_agent_contexts_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agent_contexts_workspace_id ON public.session_agent_contexts USING btree (workspace_id);


--
-- Name: ix_session_agents_context_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agents_context_id ON public.session_agents USING btree (context_id);


--
-- Name: ix_session_agents_parent_session_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agents_parent_session_agent_id ON public.session_agents USING btree (parent_session_agent_id);


--
-- Name: ix_session_agents_root_session_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_agents_root_session_agent_id ON public.session_agents USING btree (root_session_agent_id);


--
-- Name: ix_sessions_prev_refresh_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_prev_refresh_token ON public.sessions USING btree (prev_refresh_token);


--
-- Name: ix_sessions_refresh_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_refresh_token ON public.sessions USING btree (refresh_token);


--
-- Name: ix_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_user_id ON public.sessions USING btree (user_id);


--
-- Name: ix_signup_token_redemptions_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_token_redemptions_email ON public.signup_token_redemptions USING btree (email);


--
-- Name: ix_signup_token_redemptions_redeemed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_token_redemptions_redeemed_at ON public.signup_token_redemptions USING btree (redeemed_at);


--
-- Name: ix_signup_token_redemptions_signup_token_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_token_redemptions_signup_token_id ON public.signup_token_redemptions USING btree (signup_token_id);


--
-- Name: ix_signup_token_redemptions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_token_redemptions_user_id ON public.signup_token_redemptions USING btree (user_id);


--
-- Name: ix_signup_tokens_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_tokens_created_by_user_id ON public.signup_tokens USING btree (created_by_user_id);


--
-- Name: ix_signup_tokens_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_tokens_email ON public.signup_tokens USING btree (email);


--
-- Name: ix_signup_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_tokens_expires_at ON public.signup_tokens USING btree (expires_at);


--
-- Name: ix_signup_tokens_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_signup_tokens_revoked_at ON public.signup_tokens USING btree (revoked_at);


--
-- Name: ix_system_setting_audit_events_actor_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_setting_audit_events_actor_user_id ON public.system_setting_audit_events USING btree (actor_user_id);


--
-- Name: ix_system_setting_audit_events_section_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_setting_audit_events_section_created_at ON public.system_setting_audit_events USING btree (section, created_at DESC);


--
-- Name: ix_system_setting_candidates_created_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_setting_candidates_created_by_user_id ON public.system_setting_candidates USING btree (created_by_user_id);


--
-- Name: ix_system_setting_candidates_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_setting_candidates_expires_at ON public.system_setting_candidates USING btree (expires_at);


--
-- Name: ix_system_setting_health_checked_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_setting_health_checked_by_user_id ON public.system_setting_health USING btree (checked_by_user_id);


--
-- Name: ix_system_settings_updated_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_settings_updated_by_user_id ON public.system_settings USING btree (updated_by_user_id);


--
-- Name: ix_system_user_roles_granted_by_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_user_roles_granted_by_user_id ON public.system_user_roles USING btree (granted_by_user_id);


--
-- Name: ix_system_user_roles_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_user_roles_role ON public.system_user_roles USING btree (role);


--
-- Name: ix_toolkit_configs_owner_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_toolkit_configs_owner_agent_id ON public.toolkit_configs USING btree (owner_agent_id);


--
-- Name: ix_toolkit_configs_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_toolkit_configs_workspace_id ON public.toolkit_configs USING btree (workspace_id);


--
-- Name: ix_toolkit_scopes_toolkit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_toolkit_scopes_toolkit_id ON public.toolkit_scopes USING btree (toolkit_id);


--
-- Name: ix_toolkit_states_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_toolkit_states_agent_id ON public.toolkit_states USING btree (agent_id);


--
-- Name: ix_toolkit_states_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_toolkit_states_session_id ON public.toolkit_states USING btree (session_id);


--
-- Name: ix_workspace_invitations_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_invitations_email ON public.workspace_invitations USING btree (email);


--
-- Name: ix_workspace_join_requests_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_join_requests_user_id ON public.workspace_join_requests USING btree (user_id);


--
-- Name: ix_workspace_join_requests_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_join_requests_workspace_id ON public.workspace_join_requests USING btree (workspace_id);


--
-- Name: ix_workspace_runtime_profiles_infrastructure_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_runtime_profiles_infrastructure_profile_id ON public.workspace_runtime_profiles USING btree (infrastructure_profile_id);


--
-- Name: ix_workspace_runtime_profiles_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_runtime_profiles_provider_id ON public.workspace_runtime_profiles USING btree (provider_id);


--
-- Name: ix_workspace_runtime_profiles_workspace_lifecycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_runtime_profiles_workspace_lifecycle ON public.workspace_runtime_profiles USING btree (workspace_id, lifecycle);


--
-- Name: ix_workspace_users_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspace_users_workspace_id ON public.workspace_users USING btree (workspace_id);


--
-- Name: ix_workspaces_default_runtime_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workspaces_default_runtime_profile_id ON public.workspaces USING btree (default_runtime_profile_id);


--
-- Name: ix_xai_oauth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_xai_oauth_sessions_user_id ON public.xai_oauth_sessions USING btree (user_id);


--
-- Name: ix_xai_oauth_sessions_workspace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_xai_oauth_sessions_workspace_id ON public.xai_oauth_sessions USING btree (workspace_id);


--
-- Name: uq_agent_memories_agent_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_memories_agent_scope ON public.agent_memories USING btree (agent_id, name) WHERE (user_id IS NULL);


--
-- Name: uq_agent_memories_user_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_memories_user_scope ON public.agent_memories USING btree (agent_id, user_id, name) WHERE (user_id IS NOT NULL);


--
-- Name: uq_agent_runs_session_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_runs_session_pending ON public.agent_runs USING btree (session_id) WHERE (status = 'pending'::public.agent_run_status);


--
-- Name: uq_agent_runtime_add_receipts_agent_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_runtime_add_receipts_agent_idempotency ON public.agent_runtime_add_receipts USING btree (agent_id, idempotency_key);


--
-- Name: uq_agent_runtime_removal_operations_active_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_runtime_removal_operations_active_agent ON public.agent_runtime_removal_operations USING btree (agent_id) WHERE (status <> 'completed'::public.agent_runtime_removal_status);


--
-- Name: uq_agent_runtime_removal_operations_agent_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_runtime_removal_operations_agent_idempotency ON public.agent_runtime_removal_operations USING btree (agent_id, idempotency_key);


--
-- Name: uq_agent_sessions_agent_active_team_primary; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_sessions_agent_active_team_primary ON public.agent_sessions USING btree (agent_id) WHERE ((status = 'active'::public.agent_session_status) AND (primary_kind = 'team_primary'::public.agent_session_primary_kind) AND (product_mode = 'team'::public.agent_session_product_mode));


--
-- Name: uq_archived_session_retention_applications_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_archived_session_retention_applications_active ON public.archived_session_retention_applications USING btree ((1)) WHERE (status = ANY (ARRAY['pending'::public.archived_session_retention_application_status, 'running'::public.archived_session_retention_application_status, 'retry_wait'::public.archived_session_retention_application_status]));


--
-- Name: uq_chat_write_requests_creation_agent_requester_client; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_chat_write_requests_creation_agent_requester_client ON public.chat_write_requests USING btree (creation_agent_id, requester_user_id, client_request_id) WHERE (creation_agent_id IS NOT NULL);


--
-- Name: uq_events_session_external; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_events_session_external ON public.events USING btree (session_id, external_id) WHERE (external_id IS NOT NULL);


--
-- Name: uq_external_channel_access_grants_active_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_access_grants_active_agent ON public.external_channel_access_grants USING btree (agent_id, principal_id) WHERE ((scope = 'agent'::public.external_channel_access_grant_scope) AND (revoked_at IS NULL));


--
-- Name: uq_external_channel_access_grants_active_session; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_access_grants_active_session ON public.external_channel_access_grants USING btree (agent_session_id, principal_id) WHERE ((scope = 'session'::public.external_channel_access_grant_scope) AND (revoked_at IS NULL));


--
-- Name: uq_external_channel_agent_routes_single_connection; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_agent_routes_single_connection ON public.external_channel_agent_routes USING btree (connection_id) WHERE (connection_app_mode = 'single'::public.external_channel_app_mode);


--
-- Name: uq_external_channel_bindings_connected_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_bindings_connected_resource ON public.external_channel_bindings USING btree (resource_id) WHERE (disconnected_at IS NULL);


--
-- Name: uq_external_channel_channel_defaults_active_connection_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_channel_defaults_active_connection_channel ON public.external_channel_channel_defaults USING btree (connection_id, provider_channel_id) WHERE (status = 'active'::public.external_channel_channel_default_status);


--
-- Name: uq_external_channel_connections_http_callback_selector_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_connections_http_callback_selector_hash ON public.external_channel_connections USING btree (http_callback_selector_hash) WHERE (http_callback_selector_hash IS NOT NULL);


--
-- Name: uq_external_channel_connections_installation_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_connections_installation_identity ON public.external_channel_connections USING btree (provider, provider_tenant_id, provider_app_id) WHERE ((provider = 'slack'::public.external_channel_provider) AND (provider_tenant_id IS NOT NULL) AND (provider_app_id IS NOT NULL));


--
-- Name: uq_external_channel_conversation_positions_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_conversation_positions_parent ON public.external_channel_conversation_positions USING btree (connection_id, provider_channel_id) WHERE (scope_kind = 'parent_channel'::public.external_channel_conversation_scope_kind);


--
-- Name: uq_external_channel_conversation_positions_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_conversation_positions_thread ON public.external_channel_conversation_positions USING btree (connection_id, provider_channel_id, provider_thread_key) WHERE (scope_kind = 'thread'::public.external_channel_conversation_scope_kind);


--
-- Name: uq_external_channel_participation_active_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_participation_active_channel ON public.external_channel_participation_settings USING btree (connection_id, provider_parent_channel_id) WHERE (status = 'active'::public.external_channel_participation_setting_status);


--
-- Name: uq_external_channel_setup_claims_nonterminal_connection_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_external_channel_setup_claims_nonterminal_connection_channel ON public.external_channel_setup_claims USING btree (connection_id, provider_parent_channel_id) WHERE (status = ANY (ARRAY['pending_agent'::public.external_channel_setup_claim_status, 'pending_location'::public.external_channel_setup_claim_status, 'selected'::public.external_channel_setup_claim_status]));


--
-- Name: uq_github_user_installations_user_app_installation; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_github_user_installations_user_app_installation ON public.github_user_installations USING btree (user_id, platform_app_id, installation_id);


--
-- Name: uq_llm_catalogs_integration_target; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_llm_catalogs_integration_target ON public.llm_catalogs USING btree (provider_integration_id, lowerer_target) WHERE (scope = 'integration'::public.llm_catalog_scope);


--
-- Name: uq_llm_catalogs_system_scope_provider_target; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_llm_catalogs_system_scope_provider_target ON public.llm_catalogs USING btree (provider, lowerer_target) WHERE (scope = 'system'::public.llm_catalog_scope);


--
-- Name: uq_mailbox_items_session_kind_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_mailbox_items_session_kind_idempotency ON public.mailbox_items USING btree (session_id, kind, idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: uq_owner_lifecycle_jobs_account_purge; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_owner_lifecycle_jobs_account_purge ON public.owner_lifecycle_jobs USING btree (user_id) WHERE (kind = 'account_purge'::public.owner_lifecycle_kind);


--
-- Name: uq_owner_lifecycle_jobs_membership_archive; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_owner_lifecycle_jobs_membership_archive ON public.owner_lifecycle_jobs USING btree (workspace_id, user_id) WHERE (kind = 'membership_archive'::public.owner_lifecycle_kind);


--
-- Name: uq_runtime_provider_auth_bindings_bootstrap_declaration_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_runtime_provider_auth_bindings_bootstrap_declaration_active ON public.runtime_provider_auth_bindings USING btree (bootstrap_declaration_id) WHERE ((state = 'active'::public.runtime_provider_binding_state) AND (bootstrap_declaration_id IS NOT NULL));


--
-- Name: uq_runtime_provider_auth_bindings_method_subject_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_runtime_provider_auth_bindings_method_subject_active ON public.runtime_provider_auth_bindings USING btree (auth_method, subject) WHERE (state = 'active'::public.runtime_provider_binding_state);


--
-- Name: uq_toolkit_configs_owner_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_toolkit_configs_owner_agent_slug ON public.toolkit_configs USING btree (owner_agent_id, slug) WHERE (owner_agent_id IS NOT NULL);


--
-- Name: uq_toolkit_configs_shared_workspace_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_toolkit_configs_shared_workspace_slug ON public.toolkit_configs USING btree (workspace_id, slug) WHERE (owner_agent_id IS NULL);


--
-- Name: external_channel_agent_routes external_channel_agent_routes_agent_snapshot_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER external_channel_agent_routes_agent_snapshot_immutable BEFORE INSERT OR UPDATE OF agent_id_snapshot ON public.external_channel_agent_routes FOR EACH ROW EXECUTE FUNCTION public.preserve_external_channel_route_agent_snapshot();


--
-- Name: external_channel_connections external_channel_connections_app_mode_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER external_channel_connections_app_mode_immutable BEFORE UPDATE OF app_mode ON public.external_channel_connections FOR EACH ROW EXECUTE FUNCTION public.prevent_external_channel_connection_app_mode_update();


--
-- Name: agent_runtimes trg_agent_runtimes_connection_generation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_agent_runtimes_connection_generation AFTER INSERT ON public.agent_runtimes FOR EACH ROW EXECUTE FUNCTION public.initialize_agent_runtime_connection_generation();


--
-- Name: runtime_providers trg_runtime_providers_connection_generation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_runtime_providers_connection_generation AFTER INSERT ON public.runtime_providers FOR EACH ROW EXECUTE FUNCTION public.initialize_runtime_provider_connection_generation();


--
-- Name: action_execution_events action_execution_events_action_execution_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_execution_events
    ADD CONSTRAINT action_execution_events_action_execution_id_fkey FOREIGN KEY (action_execution_id) REFERENCES public.action_executions(id) ON DELETE CASCADE;


--
-- Name: action_execution_events action_execution_events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_execution_events
    ADD CONSTRAINT action_execution_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: action_executions action_executions_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_executions
    ADD CONSTRAINT action_executions_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: agent_admins agent_admins_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_admins
    ADD CONSTRAINT agent_admins_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_admins agent_admins_workspace_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_admins
    ADD CONSTRAINT agent_admins_workspace_user_id_fkey FOREIGN KEY (workspace_user_id) REFERENCES public.workspace_users(id) ON DELETE CASCADE;


--
-- Name: agent_automatic_project_items agent_automatic_project_items_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_items
    ADD CONSTRAINT agent_automatic_project_items_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent_automatic_project_settings(agent_id) ON DELETE CASCADE;


--
-- Name: agent_automatic_project_settings agent_automatic_project_setti_updated_by_workspace_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_settings
    ADD CONSTRAINT agent_automatic_project_setti_updated_by_workspace_user_id_fkey FOREIGN KEY (updated_by_workspace_user_id) REFERENCES public.workspace_users(id) ON DELETE SET NULL;


--
-- Name: agent_automatic_project_settings agent_automatic_project_settings_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_automatic_project_settings
    ADD CONSTRAINT agent_automatic_project_settings_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_avatar_cleanup_jobs agent_avatar_cleanup_jobs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_avatar_cleanup_jobs
    ADD CONSTRAINT agent_avatar_cleanup_jobs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: agent_memories agent_memories_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memories
    ADD CONSTRAINT agent_memories_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_project_catalog_entries agent_project_catalog_entries_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_catalog_entries
    ADD CONSTRAINT agent_project_catalog_entries_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_project_defaults agent_project_defaults_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_defaults
    ADD CONSTRAINT agent_project_defaults_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_project_presets agent_project_presets_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_project_presets
    ADD CONSTRAINT agent_project_presets_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_run_input_events agent_run_input_events_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_input_events
    ADD CONSTRAINT agent_run_input_events_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: agent_run_input_events agent_run_input_events_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_input_events
    ADD CONSTRAINT agent_run_input_events_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.events(id) ON DELETE CASCADE;


--
-- Name: agent_runtime_add_receipts agent_runtime_add_receipts_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_add_receipts
    ADD CONSTRAINT agent_runtime_add_receipts_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_runtime_add_receipts agent_runtime_add_receipts_agent_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_add_receipts
    ADD CONSTRAINT agent_runtime_add_receipts_agent_runtime_id_fkey FOREIGN KEY (agent_runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE CASCADE;


--
-- Name: agent_runtime_add_receipts agent_runtime_add_receipts_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_add_receipts
    ADD CONSTRAINT agent_runtime_add_receipts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: agent_runtime_removal_operations agent_runtime_removal_operations_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_removal_operations
    ADD CONSTRAINT agent_runtime_removal_operations_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_runtime_removal_operations agent_runtime_removal_operations_agent_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_removal_operations
    ADD CONSTRAINT agent_runtime_removal_operations_agent_runtime_id_fkey FOREIGN KEY (agent_runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE SET NULL;


--
-- Name: agent_runtime_removal_operations agent_runtime_removal_operations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtime_removal_operations
    ADD CONSTRAINT agent_runtime_removal_operations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: agent_runtimes agent_runtimes_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtimes
    ADD CONSTRAINT agent_runtimes_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: agent_runtimes agent_runtimes_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtimes
    ADD CONSTRAINT agent_runtimes_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;


--
-- Name: agent_session_system_prompt_snapshots agent_session_system_prompt_snapshots_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_session_system_prompt_snapshots
    ADD CONSTRAINT agent_session_system_prompt_snapshots_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: agent_session_unread_runs agent_session_unread_runs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_session_unread_runs
    ADD CONSTRAINT agent_session_unread_runs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: agent_session_unread_runs agent_session_unread_runs_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_session_unread_runs
    ADD CONSTRAINT agent_session_unread_runs_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: agent_sessions agent_sessions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: agent_sessions agent_sessions_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;


--
-- Name: agent_toolkits agent_toolkits_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_toolkits
    ADD CONSTRAINT agent_toolkits_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_toolkits agent_toolkits_toolkit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_toolkits
    ADD CONSTRAINT agent_toolkits_toolkit_id_fkey FOREIGN KEY (toolkit_id) REFERENCES public.toolkit_configs(id) ON DELETE CASCADE;


--
-- Name: agents agents_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;


--
-- Name: archived_session_purge_participant_executions archived_session_purge_participant_executions_purge_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_session_purge_participant_executions
    ADD CONSTRAINT archived_session_purge_participant_executions_purge_job_id_fkey FOREIGN KEY (purge_job_id) REFERENCES public.archived_session_purge_jobs(id) ON DELETE CASCADE;


--
-- Name: archived_session_retention_applications archived_session_retention_applicatio_requested_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.archived_session_retention_applications
    ADD CONSTRAINT archived_session_retention_applicatio_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: artifacts artifacts_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: artifacts artifacts_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: artifacts artifacts_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: chat_write_requests chat_write_requests_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_write_requests
    ADD CONSTRAINT chat_write_requests_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: chatgpt_oauth_sessions chatgpt_oauth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chatgpt_oauth_sessions
    ADD CONSTRAINT chatgpt_oauth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: chatgpt_oauth_sessions chatgpt_oauth_sessions_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chatgpt_oauth_sessions
    ADD CONSTRAINT chatgpt_oauth_sessions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: exchange_files exchange_files_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT exchange_files_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: exchange_files exchange_files_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT exchange_files_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: exchange_files exchange_files_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT exchange_files_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: external_channel_access_grants external_channel_access_grants_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_grants external_channel_access_grants_agent_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_agent_session_id_fkey FOREIGN KEY (agent_session_id) REFERENCES public.agent_sessions(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_grants external_channel_access_grants_granted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_granted_by_user_id_fkey FOREIGN KEY (granted_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_grants external_channel_access_grants_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_grants external_channel_access_grants_revoked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_grants external_channel_access_grants_source_access_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_grants
    ADD CONSTRAINT external_channel_access_grants_source_access_request_id_fkey FOREIGN KEY (source_access_request_id) REFERENCES public.external_channel_access_requests(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests external_channel_access_requests_agent_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_agent_session_id_fkey FOREIGN KEY (agent_session_id) REFERENCES public.agent_sessions(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests external_channel_access_requests_decided_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_decided_by_user_id_fkey FOREIGN KEY (decided_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests external_channel_access_requests_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests external_channel_access_requests_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_resource_id_fkey FOREIGN KEY (resource_id) REFERENCES public.external_channel_resources(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests external_channel_access_requests_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.external_channel_agent_routes(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests external_channel_access_requests_source_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT external_channel_access_requests_source_resource_id_fkey FOREIGN KEY (source_resource_id) REFERENCES public.external_channel_resources(id) ON DELETE RESTRICT;


--
-- Name: external_channel_agent_route_bot_policy_archive external_channel_agent_route_bot_policy_archive_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_route_bot_policy_archive
    ADD CONSTRAINT external_channel_agent_route_bot_policy_archive_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.external_channel_agent_routes(id) ON DELETE CASCADE;


--
-- Name: external_channel_agent_routes external_channel_agent_routes_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_routes
    ADD CONSTRAINT external_channel_agent_routes_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE SET NULL;


--
-- Name: external_channel_agent_routes external_channel_agent_routes_catalog_removed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_routes
    ADD CONSTRAINT external_channel_agent_routes_catalog_removed_by_user_id_fkey FOREIGN KEY (catalog_removed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_app_claims external_channel_app_claims_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_app_claims
    ADD CONSTRAINT external_channel_app_claims_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: external_channel_bindings external_channel_bindings_agent_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_agent_session_id_fkey FOREIGN KEY (agent_session_id) REFERENCES public.agent_sessions(id) ON DELETE RESTRICT;


--
-- Name: external_channel_bindings external_channel_bindings_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_resource_id_fkey FOREIGN KEY (resource_id) REFERENCES public.external_channel_resources(id) ON DELETE RESTRICT;


--
-- Name: external_channel_bindings external_channel_bindings_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.external_channel_agent_routes(id) ON DELETE RESTRICT;


--
-- Name: external_channel_blocks external_channel_blocks_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_blocks
    ADD CONSTRAINT external_channel_blocks_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: external_channel_blocks external_channel_blocks_blocked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_blocks
    ADD CONSTRAINT external_channel_blocks_blocked_by_user_id_fkey FOREIGN KEY (blocked_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_blocks external_channel_blocks_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_blocks
    ADD CONSTRAINT external_channel_blocks_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_blocks external_channel_blocks_removed_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_blocks
    ADD CONSTRAINT external_channel_blocks_removed_by_user_id_fkey FOREIGN KEY (removed_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_channel_defaults external_channel_channel_defaults_configured_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_channel_defaults
    ADD CONSTRAINT external_channel_channel_defaults_configured_by_user_id_fkey FOREIGN KEY (configured_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_connections external_channel_connections_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_connections
    ADD CONSTRAINT external_channel_connections_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;


--
-- Name: external_channel_conversation_positions external_channel_conversation_positions_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_conversation_positions
    ADD CONSTRAINT external_channel_conversation_positions_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_items external_channel_ingress_items_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT external_channel_ingress_items_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_items external_channel_ingress_items_conversation_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT external_channel_ingress_items_conversation_position_id_fkey FOREIGN KEY (conversation_position_id) REFERENCES public.external_channel_conversation_positions(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_items external_channel_ingress_items_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT external_channel_ingress_items_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.external_channel_ingress_owners(id) ON DELETE CASCADE;


--
-- Name: external_channel_ingress_items external_channel_ingress_items_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT external_channel_ingress_items_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_items external_channel_ingress_items_source_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_items
    ADD CONSTRAINT external_channel_ingress_items_source_resource_id_fkey FOREIGN KEY (source_resource_id) REFERENCES public.external_channel_resources(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_leases external_channel_ingress_leases_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_leases
    ADD CONSTRAINT external_channel_ingress_leases_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_binding_id_fkey FOREIGN KEY (binding_id) REFERENCES public.external_channel_bindings(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_participation_setting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_participation_setting_id_fkey FOREIGN KEY (participation_setting_id) REFERENCES public.external_channel_participation_settings(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.external_channel_agent_routes(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE RESTRICT;


--
-- Name: external_channel_ingress_owners external_channel_ingress_owners_target_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_ingress_owners
    ADD CONSTRAINT external_channel_ingress_owners_target_resource_id_fkey FOREIGN KEY (target_resource_id) REFERENCES public.external_channel_resources(id) ON DELETE RESTRICT;


--
-- Name: external_channel_interactions external_channel_interactions_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_interactions
    ADD CONSTRAINT external_channel_interactions_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: external_channel_interactions external_channel_interactions_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_interactions
    ADD CONSTRAINT external_channel_interactions_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_resources external_channel_resources_connection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_resources
    ADD CONSTRAINT external_channel_resources_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.external_channel_connections(id) ON DELETE RESTRICT;


--
-- Name: action_executions fk_action_executions_sender_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.action_executions
    ADD CONSTRAINT fk_action_executions_sender_user_id_users FOREIGN KEY (sender_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: agent_runs fk_agent_runs_parent_agent_run_id_agent_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT fk_agent_runs_parent_agent_run_id_agent_runs FOREIGN KEY (parent_agent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: agent_runs fk_agent_runs_session_id_agent_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT fk_agent_runs_session_id_agent_sessions FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: agent_runtimes fk_agent_runtimes_runtime_provider_resource_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runtimes
    ADD CONSTRAINT fk_agent_runtimes_runtime_provider_resource_id FOREIGN KEY (runtime_provider_resource_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: agent_sessions fk_agent_sessions_associated_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT fk_agent_sessions_associated_user_id_users FOREIGN KEY (associated_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: agent_sessions fk_agent_sessions_pending_command_requester_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT fk_agent_sessions_pending_command_requester_user_id_users FOREIGN KEY (pending_command_requester_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: agent_sessions fk_agent_sessions_pending_idle_continuation_run_id_agent_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT fk_agent_sessions_pending_idle_continuation_run_id_agent_runs FOREIGN KEY (pending_idle_continuation_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: agent_sessions fk_agent_sessions_stop_requester_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT fk_agent_sessions_stop_requester_user_id_users FOREIGN KEY (stop_requester_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: agents fk_agents_runtime_profile_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT fk_agents_runtime_profile_id FOREIGN KEY (runtime_profile_id) REFERENCES public.workspace_runtime_profiles(id) ON DELETE RESTRICT;


--
-- Name: chat_write_requests fk_chat_write_requests_creation_agent_id_agents; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_write_requests
    ADD CONSTRAINT fk_chat_write_requests_creation_agent_id_agents FOREIGN KEY (creation_agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: chat_write_requests fk_chat_write_requests_requester_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_write_requests
    ADD CONSTRAINT fk_chat_write_requests_requester_user_id_users FOREIGN KEY (requester_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: events fk_events_session_id_agent_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT fk_events_session_id_agent_sessions FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: exchange_files fk_exchange_files_preview_thumbnail_file_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT fk_exchange_files_preview_thumbnail_file_id FOREIGN KEY (preview_thumbnail_file_id) REFERENCES public.exchange_files(id) ON DELETE SET NULL;


--
-- Name: exchange_files fk_exchange_files_retention_root_session_id_agent_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT fk_exchange_files_retention_root_session_id_agent_sessions FOREIGN KEY (retention_root_session_id) REFERENCES public.agent_sessions(id) ON DELETE SET NULL;


--
-- Name: exchange_files fk_exchange_files_source_agent_id_agents; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT fk_exchange_files_source_agent_id_agents FOREIGN KEY (source_agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: exchange_files fk_exchange_files_source_exchange_file_id_exchange_files; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT fk_exchange_files_source_exchange_file_id_exchange_files FOREIGN KEY (source_exchange_file_id) REFERENCES public.exchange_files(id) ON DELETE RESTRICT;


--
-- Name: exchange_files fk_exchange_files_source_run_id_agent_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT fk_exchange_files_source_run_id_agent_runs FOREIGN KEY (source_run_id) REFERENCES public.agent_runs(id) ON DELETE RESTRICT;


--
-- Name: exchange_files fk_exchange_files_source_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_files
    ADD CONSTRAINT fk_exchange_files_source_user_id_users FOREIGN KEY (source_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests fk_external_channel_access_requests_connection_position; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT fk_external_channel_access_requests_connection_position FOREIGN KEY (connection_id, conversation_position_id) REFERENCES public.external_channel_conversation_positions(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests fk_external_channel_access_requests_connection_resource; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT fk_external_channel_access_requests_connection_resource FOREIGN KEY (connection_id, resource_id) REFERENCES public.external_channel_resources(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests fk_external_channel_access_requests_connection_source_resource; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT fk_external_channel_access_requests_connection_source_resource FOREIGN KEY (connection_id, source_resource_id) REFERENCES public.external_channel_resources(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_access_requests fk_external_channel_access_requests_setup_claim; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_access_requests
    ADD CONSTRAINT fk_external_channel_access_requests_setup_claim FOREIGN KEY (setup_claim_id) REFERENCES public.external_channel_setup_claims(id) ON DELETE RESTRICT;


--
-- Name: external_channel_agent_routes fk_external_channel_agent_routes_connection_app_mode; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_agent_routes
    ADD CONSTRAINT fk_external_channel_agent_routes_connection_app_mode FOREIGN KEY (connection_id, connection_app_mode) REFERENCES public.external_channel_connections(id, app_mode) ON DELETE RESTRICT;


--
-- Name: external_channel_channel_defaults fk_external_channel_channel_defaults_configured_principal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_channel_defaults
    ADD CONSTRAINT fk_external_channel_channel_defaults_configured_principal FOREIGN KEY (configured_by_principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_channel_defaults fk_external_channel_channel_defaults_connection_route; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_channel_defaults
    ADD CONSTRAINT fk_external_channel_channel_defaults_connection_route FOREIGN KEY (connection_id, route_id) REFERENCES public.external_channel_agent_routes(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_interactions fk_external_channel_interactions_setup_claim; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_interactions
    ADD CONSTRAINT fk_external_channel_interactions_setup_claim FOREIGN KEY (setup_claim_id) REFERENCES public.external_channel_setup_claims(id) ON DELETE RESTRICT;


--
-- Name: external_channel_participation_settings fk_external_channel_participation_configured_principal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_participation_settings
    ADD CONSTRAINT fk_external_channel_participation_configured_principal FOREIGN KEY (configured_by_principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: external_channel_participation_settings fk_external_channel_participation_configured_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_participation_settings
    ADD CONSTRAINT fk_external_channel_participation_configured_user FOREIGN KEY (configured_by_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: external_channel_participation_settings fk_external_channel_participation_settings_connection_route; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_participation_settings
    ADD CONSTRAINT fk_external_channel_participation_settings_connection_route FOREIGN KEY (connection_id, route_id) REFERENCES public.external_channel_agent_routes(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_setup_claims fk_external_channel_setup_claims_connection_position; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT fk_external_channel_setup_claims_connection_position FOREIGN KEY (connection_id, conversation_position_id) REFERENCES public.external_channel_conversation_positions(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_setup_claims fk_external_channel_setup_claims_connection_route; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT fk_external_channel_setup_claims_connection_route FOREIGN KEY (connection_id, route_id) REFERENCES public.external_channel_agent_routes(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_setup_claims fk_external_channel_setup_claims_connection_selected_resource; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT fk_external_channel_setup_claims_connection_selected_resource FOREIGN KEY (connection_id, selected_resource_id) REFERENCES public.external_channel_resources(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_setup_claims fk_external_channel_setup_claims_connection_selected_setting; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT fk_external_channel_setup_claims_connection_selected_setting FOREIGN KEY (connection_id, selected_setting_id) REFERENCES public.external_channel_participation_settings(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_setup_claims fk_external_channel_setup_claims_connection_source_resource; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT fk_external_channel_setup_claims_connection_source_resource FOREIGN KEY (connection_id, source_resource_id) REFERENCES public.external_channel_resources(connection_id, id) ON DELETE RESTRICT;


--
-- Name: external_channel_setup_claims fk_external_channel_setup_claims_principal; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_channel_setup_claims
    ADD CONSTRAINT fk_external_channel_setup_claims_principal FOREIGN KEY (principal_id) REFERENCES public.external_channel_principals(id) ON DELETE RESTRICT;


--
-- Name: mailbox_items fk_mailbox_items_sender_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mailbox_items
    ADD CONSTRAINT fk_mailbox_items_sender_user_id_users FOREIGN KEY (sender_user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: mailbox_items fk_mailbox_items_session_id_agent_sessions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mailbox_items
    ADD CONSTRAINT fk_mailbox_items_session_id_agent_sessions FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: model_files fk_model_files_created_run_id_agent_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_files
    ADD CONSTRAINT fk_model_files_created_run_id_agent_runs FOREIGN KEY (created_run_id) REFERENCES public.agent_runs(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_config_revisions fk_runtime_provider_config_revisions_base_revision_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT fk_runtime_provider_config_revisions_base_revision_id FOREIGN KEY (base_revision_id) REFERENCES public.runtime_provider_config_revisions(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_connections fk_runtime_provider_connections_binding_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_connections
    ADD CONSTRAINT fk_runtime_provider_connections_binding_id FOREIGN KEY (binding_id) REFERENCES public.runtime_provider_auth_bindings(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_credentials fk_runtime_provider_credentials_binding_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_credentials
    ADD CONSTRAINT fk_runtime_provider_credentials_binding_id FOREIGN KEY (binding_id) REFERENCES public.runtime_provider_auth_bindings(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_enrollment_grants fk_runtime_provider_enrollment_grants_binding_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_enrollment_grants
    ADD CONSTRAINT fk_runtime_provider_enrollment_grants_binding_id FOREIGN KEY (binding_id) REFERENCES public.runtime_provider_auth_bindings(id) ON DELETE RESTRICT;


--
-- Name: runtime_providers fk_runtime_providers_active_config_revision_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_providers
    ADD CONSTRAINT fk_runtime_providers_active_config_revision_id FOREIGN KEY (active_config_revision_id) REFERENCES public.runtime_provider_config_revisions(id) ON DELETE RESTRICT;


--
-- Name: runtime_providers fk_runtime_providers_current_contract_revision_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_providers
    ADD CONSTRAINT fk_runtime_providers_current_contract_revision_id FOREIGN KEY (current_contract_revision_id) REFERENCES public.runtime_provider_contract_revisions(id) ON DELETE RESTRICT;


--
-- Name: scheduled_tasks fk_scheduled_tasks_agent_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks
    ADD CONSTRAINT fk_scheduled_tasks_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: scheduled_tasks fk_scheduled_tasks_binding_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks
    ADD CONSTRAINT fk_scheduled_tasks_binding_id FOREIGN KEY (binding_id) REFERENCES public.external_channel_bindings(id) ON DELETE RESTRICT;


--
-- Name: scheduled_tasks fk_scheduled_tasks_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks
    ADD CONSTRAINT fk_scheduled_tasks_session_id FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE RESTRICT;


--
-- Name: scheduled_tasks fk_scheduled_tasks_workspace_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_tasks
    ADD CONSTRAINT fk_scheduled_tasks_workspace_id FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;


--
-- Name: session_agent_contexts fk_session_agent_contexts_root_session_agent_id_session_agents; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT fk_session_agent_contexts_root_session_agent_id_session_agents FOREIGN KEY (root_session_agent_id) REFERENCES public.session_agents(id) ON DELETE RESTRICT;


--
-- Name: session_agent_contexts fk_session_contexts_invalidated_removal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT fk_session_contexts_invalidated_removal_id FOREIGN KEY (working_folder_invalidated_by_removal_id) REFERENCES public.agent_runtime_removal_operations(id) ON DELETE RESTRICT;


--
-- Name: sessions fk_sessions_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_user_id FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: toolkit_configs fk_toolkit_configs_owner_agent_id_agents; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_configs
    ADD CONSTRAINT fk_toolkit_configs_owner_agent_id_agents FOREIGN KEY (owner_agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: users fk_users_primary_email_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_primary_email_id FOREIGN KEY (primary_email_id) REFERENCES public.user_emails(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: workspace_runtime_profiles fk_workspace_runtime_profiles_provider_infrastructure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_runtime_profiles
    ADD CONSTRAINT fk_workspace_runtime_profiles_provider_infrastructure FOREIGN KEY (provider_id, infrastructure_profile_id) REFERENCES public.runtime_infrastructure_profiles(provider_id, id) ON DELETE RESTRICT;


--
-- Name: workspace_users fk_workspace_users_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_users
    ADD CONSTRAINT fk_workspace_users_user_id FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workspaces fk_workspaces_default_runtime_profile_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT fk_workspaces_default_runtime_profile_id FOREIGN KEY (default_runtime_profile_id) REFERENCES public.workspace_runtime_profiles(id) ON DELETE RESTRICT;


--
-- Name: git_worktree_path_claims git_worktree_path_claims_action_execution_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_worktree_path_claims
    ADD CONSTRAINT git_worktree_path_claims_action_execution_id_fkey FOREIGN KEY (action_execution_id) REFERENCES public.action_executions(id) ON DELETE SET NULL;


--
-- Name: git_worktree_path_claims git_worktree_path_claims_agent_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_worktree_path_claims
    ADD CONSTRAINT git_worktree_path_claims_agent_runtime_id_fkey FOREIGN KEY (agent_runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE CASCADE;


--
-- Name: git_worktree_path_claims git_worktree_path_claims_root_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.git_worktree_path_claims
    ADD CONSTRAINT git_worktree_path_claims_root_session_id_fkey FOREIGN KEY (root_session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: github_user_installations github_user_installations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_user_installations
    ADD CONSTRAINT github_user_installations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: kimi_oauth_sessions kimi_oauth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kimi_oauth_sessions
    ADD CONSTRAINT kimi_oauth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: kimi_oauth_sessions kimi_oauth_sessions_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kimi_oauth_sessions
    ADD CONSTRAINT kimi_oauth_sessions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: kubernetes_sandbox_snapshots kubernetes_sandbox_snapshots_agent_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kubernetes_sandbox_snapshots
    ADD CONSTRAINT kubernetes_sandbox_snapshots_agent_runtime_id_fkey FOREIGN KEY (agent_runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE CASCADE;


--
-- Name: llm_catalog_entries llm_catalog_entries_catalog_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_entries
    ADD CONSTRAINT llm_catalog_entries_catalog_id_fkey FOREIGN KEY (catalog_id) REFERENCES public.llm_catalogs(id) ON DELETE CASCADE;


--
-- Name: llm_catalog_entries llm_catalog_entries_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_entries
    ADD CONSTRAINT llm_catalog_entries_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.llm_catalog_snapshots(id) ON DELETE CASCADE;


--
-- Name: llm_catalog_snapshots llm_catalog_snapshots_catalog_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_snapshots
    ADD CONSTRAINT llm_catalog_snapshots_catalog_id_fkey FOREIGN KEY (catalog_id) REFERENCES public.llm_catalogs(id) ON DELETE CASCADE;


--
-- Name: llm_catalog_snapshots llm_catalog_snapshots_source_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_snapshots
    ADD CONSTRAINT llm_catalog_snapshots_source_snapshot_id_fkey FOREIGN KEY (source_snapshot_id) REFERENCES public.litellm_source_snapshots(id) ON DELETE SET NULL;


--
-- Name: llm_catalog_sync_attempts llm_catalog_sync_attempts_catalog_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalog_sync_attempts
    ADD CONSTRAINT llm_catalog_sync_attempts_catalog_id_fkey FOREIGN KEY (catalog_id) REFERENCES public.llm_catalogs(id) ON DELETE CASCADE;


--
-- Name: llm_catalogs llm_catalogs_provider_integration_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_catalogs
    ADD CONSTRAINT llm_catalogs_provider_integration_id_fkey FOREIGN KEY (provider_integration_id) REFERENCES public.llm_provider_integrations(id) ON DELETE CASCADE;


--
-- Name: llm_provider_integrations llm_provider_integrations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_provider_integrations
    ADD CONSTRAINT llm_provider_integrations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: mcp_oauth_connections mcp_oauth_connections_toolkit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_oauth_connections
    ADD CONSTRAINT mcp_oauth_connections_toolkit_id_fkey FOREIGN KEY (toolkit_id) REFERENCES public.toolkit_configs(id) ON DELETE CASCADE;


--
-- Name: model_file_pins model_file_pins_model_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_file_pins
    ADD CONSTRAINT model_file_pins_model_file_id_fkey FOREIGN KEY (model_file_id) REFERENCES public.model_files(id) ON DELETE CASCADE;


--
-- Name: model_file_pins model_file_pins_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_file_pins
    ADD CONSTRAINT model_file_pins_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: model_file_pins model_file_pins_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_file_pins
    ADD CONSTRAINT model_file_pins_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: model_files model_files_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_files
    ADD CONSTRAINT model_files_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: model_files model_files_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_files
    ADD CONSTRAINT model_files_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: model_files model_files_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_files
    ADD CONSTRAINT model_files_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: password_logins password_logins_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_logins
    ADD CONSTRAINT password_logins_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: password_reset_token_redemptions password_reset_token_redemptions_password_reset_token_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_token_redemptions
    ADD CONSTRAINT password_reset_token_redemptions_password_reset_token_id_fkey FOREIGN KEY (password_reset_token_id) REFERENCES public.password_reset_tokens(id) ON DELETE CASCADE;


--
-- Name: password_reset_token_redemptions password_reset_token_redemptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_token_redemptions
    ADD CONSTRAINT password_reset_token_redemptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: password_reset_tokens password_reset_tokens_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: runtime_configuration_states runtime_configuration_states_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_configuration_states
    ADD CONSTRAINT runtime_configuration_states_runtime_id_fkey FOREIGN KEY (runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE CASCADE;


--
-- Name: runtime_infrastructure_profiles runtime_infrastructure_profiles_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_infrastructure_profiles
    ADD CONSTRAINT runtime_infrastructure_profiles_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_infrastructure_profiles runtime_infrastructure_profiles_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_infrastructure_profiles
    ADD CONSTRAINT runtime_infrastructure_profiles_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_infrastructure_profiles runtime_infrastructure_profiles_updated_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_infrastructure_profiles
    ADD CONSTRAINT runtime_infrastructure_profiles_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_audit_events runtime_provider_audit_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_audit_events
    ADD CONSTRAINT runtime_provider_audit_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_audit_events runtime_provider_audit_events_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_audit_events
    ADD CONSTRAINT runtime_provider_audit_events_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_auth_binding_audit_events runtime_provider_auth_binding_audit_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_binding_audit_events
    ADD CONSTRAINT runtime_provider_auth_binding_audit_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_auth_binding_audit_events runtime_provider_auth_binding_audit_events_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_binding_audit_events
    ADD CONSTRAINT runtime_provider_auth_binding_audit_events_binding_id_fkey FOREIGN KEY (binding_id) REFERENCES public.runtime_provider_auth_bindings(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_auth_bindings runtime_provider_auth_bindings_bootstrap_declaration_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_bindings
    ADD CONSTRAINT runtime_provider_auth_bindings_bootstrap_declaration_id_fkey FOREIGN KEY (bootstrap_declaration_id) REFERENCES public.runtime_provider_bootstrap_declarations(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_auth_bindings runtime_provider_auth_bindings_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_bindings
    ADD CONSTRAINT runtime_provider_auth_bindings_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_auth_bindings runtime_provider_auth_bindings_revoked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_auth_bindings
    ADD CONSTRAINT runtime_provider_auth_bindings_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_bootstrap_declarations runtime_provider_bootstrap_declarations_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_declarations
    ADD CONSTRAINT runtime_provider_bootstrap_declarations_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_bootstrap_declarations runtime_provider_bootstrap_declarations_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_bootstrap_declarations
    ADD CONSTRAINT runtime_provider_bootstrap_declarations_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.runtime_provider_bootstrap_sources(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_config_revisions runtime_provider_config_revisions_activated_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT runtime_provider_config_revisions_activated_by_user_id_fkey FOREIGN KEY (activated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_config_revisions runtime_provider_config_revisions_contract_revision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT runtime_provider_config_revisions_contract_revision_id_fkey FOREIGN KEY (contract_revision_id) REFERENCES public.runtime_provider_contract_revisions(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_config_revisions runtime_provider_config_revisions_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT runtime_provider_config_revisions_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_config_revisions runtime_provider_config_revisions_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_config_revisions
    ADD CONSTRAINT runtime_provider_config_revisions_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_connections runtime_provider_connections_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_connections
    ADD CONSTRAINT runtime_provider_connections_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.runtime_provider_credentials(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_connections runtime_provider_connections_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_connections
    ADD CONSTRAINT runtime_provider_connections_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_contract_revisions runtime_provider_contract_revisions_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_contract_revisions
    ADD CONSTRAINT runtime_provider_contract_revisions_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_credentials runtime_provider_credentials_issued_grant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_credentials
    ADD CONSTRAINT runtime_provider_credentials_issued_grant_id_fkey FOREIGN KEY (issued_grant_id) REFERENCES public.runtime_provider_enrollment_grants(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_credentials runtime_provider_credentials_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_credentials
    ADD CONSTRAINT runtime_provider_credentials_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_credentials runtime_provider_credentials_revoked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_credentials
    ADD CONSTRAINT runtime_provider_credentials_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_enrollment_grants runtime_provider_enrollment_grants_issued_by_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_enrollment_grants
    ADD CONSTRAINT runtime_provider_enrollment_grants_issued_by_source_id_fkey FOREIGN KEY (issued_by_source_id) REFERENCES public.runtime_provider_bootstrap_sources(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_enrollment_grants runtime_provider_enrollment_grants_issued_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_enrollment_grants
    ADD CONSTRAINT runtime_provider_enrollment_grants_issued_by_user_id_fkey FOREIGN KEY (issued_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_enrollment_grants runtime_provider_enrollment_grants_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_enrollment_grants
    ADD CONSTRAINT runtime_provider_enrollment_grants_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_enrollment_grants runtime_provider_enrollment_grants_revoked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_enrollment_grants
    ADD CONSTRAINT runtime_provider_enrollment_grants_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_provider_workspace_availability runtime_provider_workspace_availability_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_workspace_availability
    ADD CONSTRAINT runtime_provider_workspace_availability_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.runtime_providers(id) ON DELETE RESTRICT;


--
-- Name: runtime_provider_workspace_availability runtime_provider_workspace_availability_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_provider_workspace_availability
    ADD CONSTRAINT runtime_provider_workspace_availability_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE RESTRICT;


--
-- Name: runtime_providers runtime_providers_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_providers
    ADD CONSTRAINT runtime_providers_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: runtime_recreation_operation_items runtime_recreation_operation_items_operation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operation_items
    ADD CONSTRAINT runtime_recreation_operation_items_operation_id_fkey FOREIGN KEY (operation_id) REFERENCES public.runtime_recreation_operations(id) ON DELETE CASCADE;


--
-- Name: runtime_recreation_operation_items runtime_recreation_operation_items_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operation_items
    ADD CONSTRAINT runtime_recreation_operation_items_runtime_id_fkey FOREIGN KEY (runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE RESTRICT;


--
-- Name: runtime_recreation_operations runtime_recreation_operations_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operations
    ADD CONSTRAINT runtime_recreation_operations_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: runtime_recreation_operations runtime_recreation_operations_actor_workspace_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runtime_recreation_operations
    ADD CONSTRAINT runtime_recreation_operations_actor_workspace_user_id_fkey FOREIGN KEY (actor_workspace_user_id) REFERENCES public.workspace_users(id) ON DELETE SET NULL;


--
-- Name: sandbox_checkpoints sandbox_checkpoints_agent_runtime_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_checkpoints
    ADD CONSTRAINT sandbox_checkpoints_agent_runtime_id_workspace_id_fkey FOREIGN KEY (agent_runtime_id, workspace_id) REFERENCES public.agent_runtimes(id, workspace_id) ON DELETE CASCADE;


--
-- Name: sandbox_checkpoints sandbox_checkpoints_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_checkpoints
    ADD CONSTRAINT sandbox_checkpoints_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: sandbox_runtime_leases sandbox_runtime_leases_agent_runtime_id_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_runtime_leases
    ADD CONSTRAINT sandbox_runtime_leases_agent_runtime_id_workspace_id_fkey FOREIGN KEY (agent_runtime_id, workspace_id) REFERENCES public.agent_runtimes(id, workspace_id) ON DELETE CASCADE;


--
-- Name: sandbox_runtime_leases sandbox_runtime_leases_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sandbox_runtime_leases
    ADD CONSTRAINT sandbox_runtime_leases_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: session_agent_context_git_worktrees session_agent_context_git_wor_session_agent_context_projec_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_git_worktrees
    ADD CONSTRAINT session_agent_context_git_wor_session_agent_context_projec_fkey FOREIGN KEY (session_agent_context_project_id) REFERENCES public.session_agent_context_projects(id) ON DELETE SET NULL;


--
-- Name: session_agent_context_git_worktrees session_agent_context_git_work_created_by_agent_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_git_worktrees
    ADD CONSTRAINT session_agent_context_git_work_created_by_agent_session_id_fkey FOREIGN KEY (created_by_agent_session_id) REFERENCES public.agent_sessions(id) ON DELETE SET NULL;


--
-- Name: session_agent_context_git_worktrees session_agent_context_git_work_created_by_session_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_git_worktrees
    ADD CONSTRAINT session_agent_context_git_work_created_by_session_agent_id_fkey FOREIGN KEY (created_by_session_agent_id) REFERENCES public.session_agents(id) ON DELETE SET NULL;


--
-- Name: session_agent_context_git_worktrees session_agent_context_git_worktrees_action_execution_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_git_worktrees
    ADD CONSTRAINT session_agent_context_git_worktrees_action_execution_id_fkey FOREIGN KEY (action_execution_id) REFERENCES public.action_executions(id) ON DELETE SET NULL;


--
-- Name: session_agent_context_projects session_agent_context_projects_session_agent_context_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_projects
    ADD CONSTRAINT session_agent_context_projects_session_agent_context_id_fkey FOREIGN KEY (session_agent_context_id) REFERENCES public.session_agent_contexts(id) ON DELETE RESTRICT;


--
-- Name: session_agent_contexts session_agent_contexts_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT session_agent_contexts_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: session_agent_contexts session_agent_contexts_agent_runtime_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT session_agent_contexts_agent_runtime_id_fkey FOREIGN KEY (agent_runtime_id) REFERENCES public.agent_runtimes(id) ON DELETE SET NULL;


--
-- Name: session_agent_contexts session_agent_contexts_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_contexts
    ADD CONSTRAINT session_agent_contexts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: session_agent_context_git_worktrees session_agent_ctx_git_worktrees_context_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agent_context_git_worktrees
    ADD CONSTRAINT session_agent_ctx_git_worktrees_context_id_fkey FOREIGN KEY (session_agent_context_id) REFERENCES public.session_agent_contexts(id) ON DELETE RESTRICT;


--
-- Name: session_agents session_agents_agent_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT session_agents_agent_session_id_fkey FOREIGN KEY (agent_session_id) REFERENCES public.agent_sessions(id) ON DELETE RESTRICT;


--
-- Name: session_agents session_agents_context_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT session_agents_context_id_fkey FOREIGN KEY (context_id) REFERENCES public.session_agent_contexts(id) ON DELETE RESTRICT;


--
-- Name: session_agents session_agents_parent_session_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT session_agents_parent_session_agent_id_fkey FOREIGN KEY (parent_session_agent_id) REFERENCES public.session_agents(id) ON DELETE RESTRICT;


--
-- Name: session_agents session_agents_root_session_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_agents
    ADD CONSTRAINT session_agents_root_session_agent_id_fkey FOREIGN KEY (root_session_agent_id) REFERENCES public.session_agents(id) ON DELETE CASCADE;


--
-- Name: signup_token_redemptions signup_token_redemptions_signup_token_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signup_token_redemptions
    ADD CONSTRAINT signup_token_redemptions_signup_token_id_fkey FOREIGN KEY (signup_token_id) REFERENCES public.signup_tokens(id) ON DELETE CASCADE;


--
-- Name: signup_token_redemptions signup_token_redemptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signup_token_redemptions
    ADD CONSTRAINT signup_token_redemptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: signup_tokens signup_tokens_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signup_tokens
    ADD CONSTRAINT signup_tokens_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_file_lifecycle_settings system_file_lifecycle_settings_updated_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_file_lifecycle_settings
    ADD CONSTRAINT system_file_lifecycle_settings_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_setting_audit_events system_setting_audit_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_audit_events
    ADD CONSTRAINT system_setting_audit_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_setting_candidates system_setting_candidates_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_candidates
    ADD CONSTRAINT system_setting_candidates_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_setting_health system_setting_health_checked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_setting_health
    ADD CONSTRAINT system_setting_health_checked_by_user_id_fkey FOREIGN KEY (checked_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_settings system_settings_updated_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_updated_by_user_id_fkey FOREIGN KEY (updated_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_user_roles system_user_roles_granted_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_user_roles
    ADD CONSTRAINT system_user_roles_granted_by_user_id_fkey FOREIGN KEY (granted_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: system_user_roles system_user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_user_roles
    ADD CONSTRAINT system_user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: toolkit_scopes toolkit_scopes_toolkit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_scopes
    ADD CONSTRAINT toolkit_scopes_toolkit_id_fkey FOREIGN KEY (toolkit_id) REFERENCES public.toolkit_configs(id) ON DELETE CASCADE;


--
-- Name: toolkit_states toolkit_states_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_states
    ADD CONSTRAINT toolkit_states_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE RESTRICT;


--
-- Name: toolkit_states toolkit_states_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_states
    ADD CONSTRAINT toolkit_states_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.agent_sessions(id) ON DELETE CASCADE;


--
-- Name: toolkit_configs toolkits_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toolkit_configs
    ADD CONSTRAINT toolkits_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: user_emails user_emails_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_emails
    ADD CONSTRAINT user_emails_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workspace_invitations workspace_invitations_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.workspace_users(id) ON DELETE CASCADE;


--
-- Name: workspace_invitations workspace_invitations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_invitations
    ADD CONSTRAINT workspace_invitations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_join_requests workspace_join_requests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_join_requests
    ADD CONSTRAINT workspace_join_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workspace_join_requests workspace_join_requests_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_join_requests
    ADD CONSTRAINT workspace_join_requests_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_model_settings workspace_model_settings_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_model_settings
    ADD CONSTRAINT workspace_model_settings_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_runtime_profiles workspace_runtime_profiles_created_by_workspace_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_runtime_profiles
    ADD CONSTRAINT workspace_runtime_profiles_created_by_workspace_user_id_fkey FOREIGN KEY (created_by_workspace_user_id) REFERENCES public.workspace_users(id) ON DELETE SET NULL;


--
-- Name: workspace_runtime_profiles workspace_runtime_profiles_updated_by_workspace_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_runtime_profiles
    ADD CONSTRAINT workspace_runtime_profiles_updated_by_workspace_user_id_fkey FOREIGN KEY (updated_by_workspace_user_id) REFERENCES public.workspace_users(id) ON DELETE SET NULL;


--
-- Name: workspace_runtime_profiles workspace_runtime_profiles_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_runtime_profiles
    ADD CONSTRAINT workspace_runtime_profiles_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: workspace_users workspace_users_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace_users
    ADD CONSTRAINT workspace_users_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Name: xai_oauth_sessions xai_oauth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xai_oauth_sessions
    ADD CONSTRAINT xai_oauth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: xai_oauth_sessions xai_oauth_sessions_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xai_oauth_sessions
    ADD CONSTRAINT xai_oauth_sessions_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;


--
-- Baseline seed rows required by current runtime behavior
--

INSERT INTO public.system_file_lifecycle_settings (
    id,
    archived_session_retention_days,
    revision
) VALUES (1, 30, 1);

INSERT INTO public.runtime_connection_generation_cutovers (
    allocator_version,
    cutover_at
) VALUES (1, statement_timestamp());

--
-- PostgreSQL database dump complete
--
"""

_DOWNGRADE_SQL = r"""
ALTER TABLE IF EXISTS ONLY public.xai_oauth_sessions DROP CONSTRAINT IF EXISTS xai_oauth_sessions_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.xai_oauth_sessions DROP CONSTRAINT IF EXISTS xai_oauth_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_users DROP CONSTRAINT IF EXISTS workspace_users_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_runtime_profiles DROP CONSTRAINT IF EXISTS workspace_runtime_profiles_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_runtime_profiles DROP CONSTRAINT IF EXISTS workspace_runtime_profiles_updated_by_workspace_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_runtime_profiles DROP CONSTRAINT IF EXISTS workspace_runtime_profiles_created_by_workspace_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_model_settings DROP CONSTRAINT IF EXISTS workspace_model_settings_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_join_requests DROP CONSTRAINT IF EXISTS workspace_join_requests_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_join_requests DROP CONSTRAINT IF EXISTS workspace_join_requests_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_invitations DROP CONSTRAINT IF EXISTS workspace_invitations_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspace_invitations DROP CONSTRAINT IF EXISTS workspace_invitations_invited_by_fkey;
ALTER TABLE IF EXISTS ONLY public.user_emails DROP CONSTRAINT IF EXISTS user_emails_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.toolkit_configs DROP CONSTRAINT IF EXISTS toolkits_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.toolkit_states DROP CONSTRAINT IF EXISTS toolkit_states_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.toolkit_states DROP CONSTRAINT IF EXISTS toolkit_states_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.toolkit_scopes DROP CONSTRAINT IF EXISTS toolkit_scopes_toolkit_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_user_roles DROP CONSTRAINT IF EXISTS system_user_roles_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_user_roles DROP CONSTRAINT IF EXISTS system_user_roles_granted_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_settings DROP CONSTRAINT IF EXISTS system_settings_updated_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_setting_health DROP CONSTRAINT IF EXISTS system_setting_health_checked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_setting_candidates DROP CONSTRAINT IF EXISTS system_setting_candidates_created_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_setting_audit_events DROP CONSTRAINT IF EXISTS system_setting_audit_events_actor_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.system_file_lifecycle_settings DROP CONSTRAINT IF EXISTS system_file_lifecycle_settings_updated_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.signup_tokens DROP CONSTRAINT IF EXISTS signup_tokens_created_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.signup_token_redemptions DROP CONSTRAINT IF EXISTS signup_token_redemptions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.signup_token_redemptions DROP CONSTRAINT IF EXISTS signup_token_redemptions_signup_token_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS session_agents_root_session_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS session_agents_parent_session_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS session_agents_context_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS session_agents_agent_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_git_worktrees DROP CONSTRAINT IF EXISTS session_agent_ctx_git_worktrees_context_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS session_agent_contexts_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS session_agent_contexts_agent_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS session_agent_contexts_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_projects DROP CONSTRAINT IF EXISTS session_agent_context_projects_session_agent_context_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_git_worktrees DROP CONSTRAINT IF EXISTS session_agent_context_git_worktrees_action_execution_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_git_worktrees DROP CONSTRAINT IF EXISTS session_agent_context_git_work_created_by_session_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_git_worktrees DROP CONSTRAINT IF EXISTS session_agent_context_git_work_created_by_agent_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_git_worktrees DROP CONSTRAINT IF EXISTS session_agent_context_git_wor_session_agent_context_projec_fkey;
ALTER TABLE IF EXISTS ONLY public.sandbox_runtime_leases DROP CONSTRAINT IF EXISTS sandbox_runtime_leases_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.sandbox_runtime_leases DROP CONSTRAINT IF EXISTS sandbox_runtime_leases_agent_runtime_id_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.sandbox_checkpoints DROP CONSTRAINT IF EXISTS sandbox_checkpoints_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.sandbox_checkpoints DROP CONSTRAINT IF EXISTS sandbox_checkpoints_agent_runtime_id_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operations DROP CONSTRAINT IF EXISTS runtime_recreation_operations_actor_workspace_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operations DROP CONSTRAINT IF EXISTS runtime_recreation_operations_actor_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operation_items DROP CONSTRAINT IF EXISTS runtime_recreation_operation_items_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operation_items DROP CONSTRAINT IF EXISTS runtime_recreation_operation_items_operation_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_providers DROP CONSTRAINT IF EXISTS runtime_providers_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_workspace_availability DROP CONSTRAINT IF EXISTS runtime_provider_workspace_availability_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_workspace_availability DROP CONSTRAINT IF EXISTS runtime_provider_workspace_availability_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_enrollment_grants DROP CONSTRAINT IF EXISTS runtime_provider_enrollment_grants_revoked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_enrollment_grants DROP CONSTRAINT IF EXISTS runtime_provider_enrollment_grants_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_enrollment_grants DROP CONSTRAINT IF EXISTS runtime_provider_enrollment_grants_issued_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_enrollment_grants DROP CONSTRAINT IF EXISTS runtime_provider_enrollment_grants_issued_by_source_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_credentials DROP CONSTRAINT IF EXISTS runtime_provider_credentials_revoked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_credentials DROP CONSTRAINT IF EXISTS runtime_provider_credentials_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_credentials DROP CONSTRAINT IF EXISTS runtime_provider_credentials_issued_grant_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_contract_revisions DROP CONSTRAINT IF EXISTS runtime_provider_contract_revisions_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_connections DROP CONSTRAINT IF EXISTS runtime_provider_connections_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_connections DROP CONSTRAINT IF EXISTS runtime_provider_connections_credential_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS runtime_provider_config_revisions_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS runtime_provider_config_revisions_created_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS runtime_provider_config_revisions_contract_revision_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS runtime_provider_config_revisions_activated_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_declarations DROP CONSTRAINT IF EXISTS runtime_provider_bootstrap_declarations_source_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_declarations DROP CONSTRAINT IF EXISTS runtime_provider_bootstrap_declarations_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_bindings DROP CONSTRAINT IF EXISTS runtime_provider_auth_bindings_revoked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_bindings DROP CONSTRAINT IF EXISTS runtime_provider_auth_bindings_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_bindings DROP CONSTRAINT IF EXISTS runtime_provider_auth_bindings_bootstrap_declaration_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_binding_audit_events DROP CONSTRAINT IF EXISTS runtime_provider_auth_binding_audit_events_binding_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_binding_audit_events DROP CONSTRAINT IF EXISTS runtime_provider_auth_binding_audit_events_actor_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_audit_events DROP CONSTRAINT IF EXISTS runtime_provider_audit_events_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_audit_events DROP CONSTRAINT IF EXISTS runtime_provider_audit_events_actor_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_infrastructure_profiles DROP CONSTRAINT IF EXISTS runtime_infrastructure_profiles_updated_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_infrastructure_profiles DROP CONSTRAINT IF EXISTS runtime_infrastructure_profiles_provider_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_infrastructure_profiles DROP CONSTRAINT IF EXISTS runtime_infrastructure_profiles_created_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.runtime_configuration_states DROP CONSTRAINT IF EXISTS runtime_configuration_states_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.password_reset_tokens DROP CONSTRAINT IF EXISTS password_reset_tokens_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.password_reset_tokens DROP CONSTRAINT IF EXISTS password_reset_tokens_created_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.password_reset_token_redemptions DROP CONSTRAINT IF EXISTS password_reset_token_redemptions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.password_reset_token_redemptions DROP CONSTRAINT IF EXISTS password_reset_token_redemptions_password_reset_token_id_fkey;
ALTER TABLE IF EXISTS ONLY public.password_logins DROP CONSTRAINT IF EXISTS password_logins_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.model_files DROP CONSTRAINT IF EXISTS model_files_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.model_files DROP CONSTRAINT IF EXISTS model_files_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.model_files DROP CONSTRAINT IF EXISTS model_files_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.model_file_pins DROP CONSTRAINT IF EXISTS model_file_pins_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.model_file_pins DROP CONSTRAINT IF EXISTS model_file_pins_run_id_fkey;
ALTER TABLE IF EXISTS ONLY public.model_file_pins DROP CONSTRAINT IF EXISTS model_file_pins_model_file_id_fkey;
ALTER TABLE IF EXISTS ONLY public.mcp_oauth_connections DROP CONSTRAINT IF EXISTS mcp_oauth_connections_toolkit_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_provider_integrations DROP CONSTRAINT IF EXISTS llm_provider_integrations_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalogs DROP CONSTRAINT IF EXISTS llm_catalogs_provider_integration_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_sync_attempts DROP CONSTRAINT IF EXISTS llm_catalog_sync_attempts_catalog_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_snapshots DROP CONSTRAINT IF EXISTS llm_catalog_snapshots_source_snapshot_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_snapshots DROP CONSTRAINT IF EXISTS llm_catalog_snapshots_catalog_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_entries DROP CONSTRAINT IF EXISTS llm_catalog_entries_snapshot_id_fkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_entries DROP CONSTRAINT IF EXISTS llm_catalog_entries_catalog_id_fkey;
ALTER TABLE IF EXISTS ONLY public.kubernetes_sandbox_snapshots DROP CONSTRAINT IF EXISTS kubernetes_sandbox_snapshots_agent_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.kimi_oauth_sessions DROP CONSTRAINT IF EXISTS kimi_oauth_sessions_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.kimi_oauth_sessions DROP CONSTRAINT IF EXISTS kimi_oauth_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.github_user_installations DROP CONSTRAINT IF EXISTS github_user_installations_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.git_worktree_path_claims DROP CONSTRAINT IF EXISTS git_worktree_path_claims_root_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.git_worktree_path_claims DROP CONSTRAINT IF EXISTS git_worktree_path_claims_agent_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.git_worktree_path_claims DROP CONSTRAINT IF EXISTS git_worktree_path_claims_action_execution_id_fkey;
ALTER TABLE IF EXISTS ONLY public.workspaces DROP CONSTRAINT IF EXISTS fk_workspaces_default_runtime_profile_id;
ALTER TABLE IF EXISTS ONLY public.workspace_users DROP CONSTRAINT IF EXISTS fk_workspace_users_user_id;
ALTER TABLE IF EXISTS ONLY public.workspace_runtime_profiles DROP CONSTRAINT IF EXISTS fk_workspace_runtime_profiles_provider_infrastructure;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS fk_users_primary_email_id;
ALTER TABLE IF EXISTS ONLY public.toolkit_configs DROP CONSTRAINT IF EXISTS fk_toolkit_configs_owner_agent_id_agents;
ALTER TABLE IF EXISTS ONLY public.sessions DROP CONSTRAINT IF EXISTS fk_sessions_user_id;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS fk_session_contexts_invalidated_removal_id;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS fk_session_agent_contexts_root_session_agent_id_session_agents;
ALTER TABLE IF EXISTS ONLY public.scheduled_tasks DROP CONSTRAINT IF EXISTS fk_scheduled_tasks_workspace_id;
ALTER TABLE IF EXISTS ONLY public.scheduled_tasks DROP CONSTRAINT IF EXISTS fk_scheduled_tasks_session_id;
ALTER TABLE IF EXISTS ONLY public.scheduled_tasks DROP CONSTRAINT IF EXISTS fk_scheduled_tasks_binding_id;
ALTER TABLE IF EXISTS ONLY public.scheduled_tasks DROP CONSTRAINT IF EXISTS fk_scheduled_tasks_agent_id;
ALTER TABLE IF EXISTS ONLY public.runtime_providers DROP CONSTRAINT IF EXISTS fk_runtime_providers_current_contract_revision_id;
ALTER TABLE IF EXISTS ONLY public.runtime_providers DROP CONSTRAINT IF EXISTS fk_runtime_providers_active_config_revision_id;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_enrollment_grants DROP CONSTRAINT IF EXISTS fk_runtime_provider_enrollment_grants_binding_id;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_credentials DROP CONSTRAINT IF EXISTS fk_runtime_provider_credentials_binding_id;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_connections DROP CONSTRAINT IF EXISTS fk_runtime_provider_connections_binding_id;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS fk_runtime_provider_config_revisions_base_revision_id;
ALTER TABLE IF EXISTS ONLY public.model_files DROP CONSTRAINT IF EXISTS fk_model_files_created_run_id_agent_runs;
ALTER TABLE IF EXISTS ONLY public.mailbox_items DROP CONSTRAINT IF EXISTS fk_mailbox_items_session_id_agent_sessions;
ALTER TABLE IF EXISTS ONLY public.mailbox_items DROP CONSTRAINT IF EXISTS fk_mailbox_items_sender_user_id_users;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS fk_external_channel_setup_claims_principal;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS fk_external_channel_setup_claims_connection_source_resource;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS fk_external_channel_setup_claims_connection_selected_setting;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS fk_external_channel_setup_claims_connection_selected_resource;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS fk_external_channel_setup_claims_connection_route;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS fk_external_channel_setup_claims_connection_position;
ALTER TABLE IF EXISTS ONLY public.external_channel_participation_settings DROP CONSTRAINT IF EXISTS fk_external_channel_participation_settings_connection_route;
ALTER TABLE IF EXISTS ONLY public.external_channel_participation_settings DROP CONSTRAINT IF EXISTS fk_external_channel_participation_configured_user;
ALTER TABLE IF EXISTS ONLY public.external_channel_participation_settings DROP CONSTRAINT IF EXISTS fk_external_channel_participation_configured_principal;
ALTER TABLE IF EXISTS ONLY public.external_channel_interactions DROP CONSTRAINT IF EXISTS fk_external_channel_interactions_setup_claim;
ALTER TABLE IF EXISTS ONLY public.external_channel_channel_defaults DROP CONSTRAINT IF EXISTS fk_external_channel_channel_defaults_connection_route;
ALTER TABLE IF EXISTS ONLY public.external_channel_channel_defaults DROP CONSTRAINT IF EXISTS fk_external_channel_channel_defaults_configured_principal;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_routes DROP CONSTRAINT IF EXISTS fk_external_channel_agent_routes_connection_app_mode;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS fk_external_channel_access_requests_setup_claim;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS fk_external_channel_access_requests_connection_source_resource;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS fk_external_channel_access_requests_connection_resource;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS fk_external_channel_access_requests_connection_position;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS fk_exchange_files_source_user_id_users;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS fk_exchange_files_source_run_id_agent_runs;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS fk_exchange_files_source_exchange_file_id_exchange_files;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS fk_exchange_files_source_agent_id_agents;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS fk_exchange_files_retention_root_session_id_agent_sessions;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS fk_exchange_files_preview_thumbnail_file_id;
ALTER TABLE IF EXISTS ONLY public.events DROP CONSTRAINT IF EXISTS fk_events_session_id_agent_sessions;
ALTER TABLE IF EXISTS ONLY public.chat_write_requests DROP CONSTRAINT IF EXISTS fk_chat_write_requests_requester_user_id_users;
ALTER TABLE IF EXISTS ONLY public.chat_write_requests DROP CONSTRAINT IF EXISTS fk_chat_write_requests_creation_agent_id_agents;
ALTER TABLE IF EXISTS ONLY public.agents DROP CONSTRAINT IF EXISTS fk_agents_runtime_profile_id;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS fk_agent_sessions_stop_requester_user_id_users;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS fk_agent_sessions_pending_idle_continuation_run_id_agent_runs;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS fk_agent_sessions_pending_command_requester_user_id_users;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS fk_agent_sessions_associated_user_id_users;
ALTER TABLE IF EXISTS ONLY public.agent_runtimes DROP CONSTRAINT IF EXISTS fk_agent_runtimes_runtime_provider_resource_id;
ALTER TABLE IF EXISTS ONLY public.agent_runs DROP CONSTRAINT IF EXISTS fk_agent_runs_session_id_agent_sessions;
ALTER TABLE IF EXISTS ONLY public.agent_runs DROP CONSTRAINT IF EXISTS fk_agent_runs_parent_agent_run_id_agent_runs;
ALTER TABLE IF EXISTS ONLY public.action_executions DROP CONSTRAINT IF EXISTS fk_action_executions_sender_user_id_users;
ALTER TABLE IF EXISTS ONLY public.external_channel_resources DROP CONSTRAINT IF EXISTS external_channel_resources_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_interactions DROP CONSTRAINT IF EXISTS external_channel_interactions_principal_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_interactions DROP CONSTRAINT IF EXISTS external_channel_interactions_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_target_resource_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_route_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_participation_setting_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_binding_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_leases DROP CONSTRAINT IF EXISTS external_channel_ingress_leases_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS external_channel_ingress_items_source_resource_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS external_channel_ingress_items_principal_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS external_channel_ingress_items_owner_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS external_channel_ingress_items_conversation_position_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS external_channel_ingress_items_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_conversation_positions DROP CONSTRAINT IF EXISTS external_channel_conversation_positions_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_connections DROP CONSTRAINT IF EXISTS external_channel_connections_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_channel_defaults DROP CONSTRAINT IF EXISTS external_channel_channel_defaults_configured_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_blocks DROP CONSTRAINT IF EXISTS external_channel_blocks_removed_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_blocks DROP CONSTRAINT IF EXISTS external_channel_blocks_principal_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_blocks DROP CONSTRAINT IF EXISTS external_channel_blocks_blocked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_blocks DROP CONSTRAINT IF EXISTS external_channel_blocks_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_bindings DROP CONSTRAINT IF EXISTS external_channel_bindings_route_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_bindings DROP CONSTRAINT IF EXISTS external_channel_bindings_resource_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_bindings DROP CONSTRAINT IF EXISTS external_channel_bindings_agent_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_app_claims DROP CONSTRAINT IF EXISTS external_channel_app_claims_connection_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_routes DROP CONSTRAINT IF EXISTS external_channel_agent_routes_catalog_removed_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_routes DROP CONSTRAINT IF EXISTS external_channel_agent_routes_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_route_bot_policy_archive DROP CONSTRAINT IF EXISTS external_channel_agent_route_bot_policy_archive_route_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_source_resource_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_route_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_resource_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_principal_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_decided_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_agent_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_source_access_request_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_revoked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_principal_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_granted_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_agent_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS exchange_files_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS exchange_files_created_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS exchange_files_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.chatgpt_oauth_sessions DROP CONSTRAINT IF EXISTS chatgpt_oauth_sessions_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.chatgpt_oauth_sessions DROP CONSTRAINT IF EXISTS chatgpt_oauth_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.chat_write_requests DROP CONSTRAINT IF EXISTS chat_write_requests_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.artifacts DROP CONSTRAINT IF EXISTS artifacts_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.artifacts DROP CONSTRAINT IF EXISTS artifacts_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.artifacts DROP CONSTRAINT IF EXISTS artifacts_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.archived_session_retention_applications DROP CONSTRAINT IF EXISTS archived_session_retention_applicatio_requested_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.archived_session_purge_participant_executions DROP CONSTRAINT IF EXISTS archived_session_purge_participant_executions_purge_job_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agents DROP CONSTRAINT IF EXISTS agents_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_toolkits DROP CONSTRAINT IF EXISTS agent_toolkits_toolkit_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_toolkits DROP CONSTRAINT IF EXISTS agent_toolkits_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS agent_sessions_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS agent_sessions_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_session_unread_runs DROP CONSTRAINT IF EXISTS agent_session_unread_runs_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_session_unread_runs DROP CONSTRAINT IF EXISTS agent_session_unread_runs_run_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_session_system_prompt_snapshots DROP CONSTRAINT IF EXISTS agent_session_system_prompt_snapshots_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtimes DROP CONSTRAINT IF EXISTS agent_runtimes_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtimes DROP CONSTRAINT IF EXISTS agent_runtimes_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_removal_operations DROP CONSTRAINT IF EXISTS agent_runtime_removal_operations_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_removal_operations DROP CONSTRAINT IF EXISTS agent_runtime_removal_operations_agent_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_removal_operations DROP CONSTRAINT IF EXISTS agent_runtime_removal_operations_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_add_receipts DROP CONSTRAINT IF EXISTS agent_runtime_add_receipts_workspace_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_add_receipts DROP CONSTRAINT IF EXISTS agent_runtime_add_receipts_agent_runtime_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_add_receipts DROP CONSTRAINT IF EXISTS agent_runtime_add_receipts_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_run_input_events DROP CONSTRAINT IF EXISTS agent_run_input_events_event_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_run_input_events DROP CONSTRAINT IF EXISTS agent_run_input_events_agent_run_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_project_presets DROP CONSTRAINT IF EXISTS agent_project_presets_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_project_defaults DROP CONSTRAINT IF EXISTS agent_project_defaults_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_project_catalog_entries DROP CONSTRAINT IF EXISTS agent_project_catalog_entries_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_memories DROP CONSTRAINT IF EXISTS agent_memories_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_avatar_cleanup_jobs DROP CONSTRAINT IF EXISTS agent_avatar_cleanup_jobs_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_settings DROP CONSTRAINT IF EXISTS agent_automatic_project_settings_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_settings DROP CONSTRAINT IF EXISTS agent_automatic_project_setti_updated_by_workspace_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_items DROP CONSTRAINT IF EXISTS agent_automatic_project_items_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_admins DROP CONSTRAINT IF EXISTS agent_admins_workspace_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_admins DROP CONSTRAINT IF EXISTS agent_admins_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.action_executions DROP CONSTRAINT IF EXISTS action_executions_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.action_execution_events DROP CONSTRAINT IF EXISTS action_execution_events_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.action_execution_events DROP CONSTRAINT IF EXISTS action_execution_events_action_execution_id_fkey;
DROP TRIGGER IF EXISTS trg_runtime_providers_connection_generation ON public.runtime_providers;
DROP TRIGGER IF EXISTS trg_agent_runtimes_connection_generation ON public.agent_runtimes;
DROP TRIGGER IF EXISTS external_channel_connections_app_mode_immutable ON public.external_channel_connections;
DROP TRIGGER IF EXISTS external_channel_agent_routes_agent_snapshot_immutable ON public.external_channel_agent_routes;
DROP INDEX IF EXISTS public.uq_toolkit_configs_shared_workspace_slug;
DROP INDEX IF EXISTS public.uq_toolkit_configs_owner_agent_slug;
DROP INDEX IF EXISTS public.uq_runtime_provider_auth_bindings_method_subject_active;
DROP INDEX IF EXISTS public.uq_runtime_provider_auth_bindings_bootstrap_declaration_active;
DROP INDEX IF EXISTS public.uq_owner_lifecycle_jobs_membership_archive;
DROP INDEX IF EXISTS public.uq_owner_lifecycle_jobs_account_purge;
DROP INDEX IF EXISTS public.uq_mailbox_items_session_kind_idempotency;
DROP INDEX IF EXISTS public.uq_llm_catalogs_system_scope_provider_target;
DROP INDEX IF EXISTS public.uq_llm_catalogs_integration_target;
DROP INDEX IF EXISTS public.uq_github_user_installations_user_app_installation;
DROP INDEX IF EXISTS public.uq_external_channel_setup_claims_nonterminal_connection_channel;
DROP INDEX IF EXISTS public.uq_external_channel_participation_active_channel;
DROP INDEX IF EXISTS public.uq_external_channel_conversation_positions_thread;
DROP INDEX IF EXISTS public.uq_external_channel_conversation_positions_parent;
DROP INDEX IF EXISTS public.uq_external_channel_connections_installation_identity;
DROP INDEX IF EXISTS public.uq_external_channel_connections_http_callback_selector_hash;
DROP INDEX IF EXISTS public.uq_external_channel_channel_defaults_active_connection_channel;
DROP INDEX IF EXISTS public.uq_external_channel_bindings_connected_resource;
DROP INDEX IF EXISTS public.uq_external_channel_agent_routes_single_connection;
DROP INDEX IF EXISTS public.uq_external_channel_access_grants_active_session;
DROP INDEX IF EXISTS public.uq_external_channel_access_grants_active_agent;
DROP INDEX IF EXISTS public.uq_events_session_external;
DROP INDEX IF EXISTS public.uq_chat_write_requests_creation_agent_requester_client;
DROP INDEX IF EXISTS public.uq_archived_session_retention_applications_active;
DROP INDEX IF EXISTS public.uq_agent_sessions_agent_active_team_primary;
DROP INDEX IF EXISTS public.uq_agent_runtime_removal_operations_agent_idempotency;
DROP INDEX IF EXISTS public.uq_agent_runtime_removal_operations_active_agent;
DROP INDEX IF EXISTS public.uq_agent_runtime_add_receipts_agent_idempotency;
DROP INDEX IF EXISTS public.uq_agent_runs_session_pending;
DROP INDEX IF EXISTS public.uq_agent_memories_user_scope;
DROP INDEX IF EXISTS public.uq_agent_memories_agent_scope;
DROP INDEX IF EXISTS public.ix_xai_oauth_sessions_workspace_id;
DROP INDEX IF EXISTS public.ix_xai_oauth_sessions_user_id;
DROP INDEX IF EXISTS public.ix_workspaces_default_runtime_profile_id;
DROP INDEX IF EXISTS public.ix_workspace_users_workspace_id;
DROP INDEX IF EXISTS public.ix_workspace_runtime_profiles_workspace_lifecycle;
DROP INDEX IF EXISTS public.ix_workspace_runtime_profiles_provider_id;
DROP INDEX IF EXISTS public.ix_workspace_runtime_profiles_infrastructure_profile_id;
DROP INDEX IF EXISTS public.ix_workspace_join_requests_workspace_id;
DROP INDEX IF EXISTS public.ix_workspace_join_requests_user_id;
DROP INDEX IF EXISTS public.ix_workspace_invitations_email;
DROP INDEX IF EXISTS public.ix_toolkit_states_session_id;
DROP INDEX IF EXISTS public.ix_toolkit_states_agent_id;
DROP INDEX IF EXISTS public.ix_toolkit_scopes_toolkit_id;
DROP INDEX IF EXISTS public.ix_toolkit_configs_workspace_id;
DROP INDEX IF EXISTS public.ix_toolkit_configs_owner_agent_id;
DROP INDEX IF EXISTS public.ix_system_user_roles_role;
DROP INDEX IF EXISTS public.ix_system_user_roles_granted_by_user_id;
DROP INDEX IF EXISTS public.ix_system_settings_updated_by_user_id;
DROP INDEX IF EXISTS public.ix_system_setting_health_checked_by_user_id;
DROP INDEX IF EXISTS public.ix_system_setting_candidates_expires_at;
DROP INDEX IF EXISTS public.ix_system_setting_candidates_created_by_user_id;
DROP INDEX IF EXISTS public.ix_system_setting_audit_events_section_created_at;
DROP INDEX IF EXISTS public.ix_system_setting_audit_events_actor_user_id;
DROP INDEX IF EXISTS public.ix_signup_tokens_revoked_at;
DROP INDEX IF EXISTS public.ix_signup_tokens_expires_at;
DROP INDEX IF EXISTS public.ix_signup_tokens_email;
DROP INDEX IF EXISTS public.ix_signup_tokens_created_by_user_id;
DROP INDEX IF EXISTS public.ix_signup_token_redemptions_user_id;
DROP INDEX IF EXISTS public.ix_signup_token_redemptions_signup_token_id;
DROP INDEX IF EXISTS public.ix_signup_token_redemptions_redeemed_at;
DROP INDEX IF EXISTS public.ix_signup_token_redemptions_email;
DROP INDEX IF EXISTS public.ix_sessions_user_id;
DROP INDEX IF EXISTS public.ix_sessions_refresh_token;
DROP INDEX IF EXISTS public.ix_sessions_prev_refresh_token;
DROP INDEX IF EXISTS public.ix_session_agents_root_session_agent_id;
DROP INDEX IF EXISTS public.ix_session_agents_parent_session_agent_id;
DROP INDEX IF EXISTS public.ix_session_agents_context_id;
DROP INDEX IF EXISTS public.ix_session_agent_contexts_workspace_id;
DROP INDEX IF EXISTS public.ix_session_agent_contexts_agent_runtime_id;
DROP INDEX IF EXISTS public.ix_session_agent_contexts_agent_id;
DROP INDEX IF EXISTS public.ix_session_agent_context_projects_context_id;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_worktree_path;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_status;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_context_project_id;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_context_id_status;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_context_id;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_branch_name;
DROP INDEX IF EXISTS public.ix_session_agent_context_git_worktrees_action_execution_id;
DROP INDEX IF EXISTS public.ix_scheduled_tasks_session_id;
DROP INDEX IF EXISTS public.ix_scheduled_tasks_next_eligible_at_id;
DROP INDEX IF EXISTS public.ix_scheduled_tasks_binding_id;
DROP INDEX IF EXISTS public.ix_scheduled_tasks_active_cycle_id;
DROP INDEX IF EXISTS public.ix_scheduled_task_states_next_run_at;
DROP INDEX IF EXISTS public.ix_scheduled_task_states_lease_until;
DROP INDEX IF EXISTS public.ix_sandbox_runtime_leases_workspace_id;
DROP INDEX IF EXISTS public.ix_sandbox_runtime_leases_stale;
DROP INDEX IF EXISTS public.ix_sandbox_runtime_leases_provider_state;
DROP INDEX IF EXISTS public.ix_sandbox_runtime_leases_active_runtime;
DROP INDEX IF EXISTS public.ix_sandbox_checkpoints_workspace_id;
DROP INDEX IF EXISTS public.ix_sandbox_checkpoints_agent_runtime_id_invalidated_at;
DROP INDEX IF EXISTS public.ix_sandbox_checkpoints_agent_runtime_id_created_at;
DROP INDEX IF EXISTS public.ix_runtime_recreation_operations_target;
DROP INDEX IF EXISTS public.ix_runtime_recreation_operations_status;
DROP INDEX IF EXISTS public.ix_runtime_recreation_operation_items_operation_status;
DROP INDEX IF EXISTS public.ix_runtime_providers_workspace_id;
DROP INDEX IF EXISTS public.ix_runtime_providers_lifecycle_enabled;
DROP INDEX IF EXISTS public.ix_runtime_providers_kind;
DROP INDEX IF EXISTS public.ix_runtime_providers_enabled_scope;
DROP INDEX IF EXISTS public.ix_runtime_provider_workspace_availability_workspace_id;
DROP INDEX IF EXISTS public.ix_runtime_provider_enrollment_grants_provider_state;
DROP INDEX IF EXISTS public.ix_runtime_provider_enrollment_grants_expires_at;
DROP INDEX IF EXISTS public.ix_runtime_provider_credentials_provider_state;
DROP INDEX IF EXISTS public.ix_runtime_provider_credentials_expires_at;
DROP INDEX IF EXISTS public.ix_runtime_provider_contract_revisions_provider_created;
DROP INDEX IF EXISTS public.ix_runtime_provider_connections_provider_status;
DROP INDEX IF EXISTS public.ix_runtime_provider_connections_credential_status;
DROP INDEX IF EXISTS public.ix_runtime_provider_connections_binding_status;
DROP INDEX IF EXISTS public.ix_runtime_provider_config_revisions_validation_request;
DROP INDEX IF EXISTS public.ix_runtime_provider_config_revisions_provider_state;
DROP INDEX IF EXISTS public.ix_runtime_provider_bootstrap_sources_adapter_kind;
DROP INDEX IF EXISTS public.ix_runtime_provider_auth_bindings_provider_state;
DROP INDEX IF EXISTS public.ix_runtime_provider_auth_bindings_method_subject_state;
DROP INDEX IF EXISTS public.ix_runtime_provider_auth_binding_audit_events_binding_created;
DROP INDEX IF EXISTS public.ix_runtime_provider_audit_events_provider_created;
DROP INDEX IF EXISTS public.ix_runtime_infrastructure_profiles_provider_lifecycle;
DROP INDEX IF EXISTS public.ix_runtime_infrastructure_profiles_kind;
DROP INDEX IF EXISTS public.ix_runtime_configuration_reconcile_tasks_status_available;
DROP INDEX IF EXISTS public.ix_runtime_configuration_reconcile_tasks_source;
DROP INDEX IF EXISTS public.ix_password_reset_tokens_user_id;
DROP INDEX IF EXISTS public.ix_password_reset_tokens_revoked_at;
DROP INDEX IF EXISTS public.ix_password_reset_tokens_expires_at;
DROP INDEX IF EXISTS public.ix_password_reset_tokens_created_by_user_id;
DROP INDEX IF EXISTS public.ix_password_reset_token_redemptions_user_id;
DROP INDEX IF EXISTS public.ix_password_reset_token_redemptions_redeemed_at;
DROP INDEX IF EXISTS public.ix_password_reset_token_redemptions_password_reset_token_id;
DROP INDEX IF EXISTS public.ix_owner_lifecycle_jobs_status_next_attempt_at;
DROP INDEX IF EXISTS public.ix_model_files_workspace_id;
DROP INDEX IF EXISTS public.ix_model_files_session_status;
DROP INDEX IF EXISTS public.ix_model_file_pins_run_id;
DROP INDEX IF EXISTS public.ix_model_file_pins_model_file_id;
DROP INDEX IF EXISTS public.ix_mcp_oauth_connections_toolkit_id;
DROP INDEX IF EXISTS public.ix_mailbox_items_session_order;
DROP INDEX IF EXISTS public.ix_mailbox_items_session_id_scheduling_mode;
DROP INDEX IF EXISTS public.ix_mailbox_items_session_id;
DROP INDEX IF EXISTS public.ix_mailbox_items_kind;
DROP INDEX IF EXISTS public.ix_llm_provider_integrations_workspace_id;
DROP INDEX IF EXISTS public.ix_llm_catalogs_provider_integration_id;
DROP INDEX IF EXISTS public.ix_llm_catalog_sync_attempts_catalog_id;
DROP INDEX IF EXISTS public.ix_llm_catalog_snapshots_catalog_id;
DROP INDEX IF EXISTS public.ix_llm_catalog_entries_snapshot_id;
DROP INDEX IF EXISTS public.ix_llm_catalog_entries_catalog_model;
DROP INDEX IF EXISTS public.ix_llm_catalog_entries_catalog_display;
DROP INDEX IF EXISTS public.ix_kubernetes_sandbox_snapshots_agent_runtime_id_created_at;
DROP INDEX IF EXISTS public.ix_kimi_oauth_sessions_workspace_id;
DROP INDEX IF EXISTS public.ix_kimi_oauth_sessions_user_id;
DROP INDEX IF EXISTS public.ix_github_user_installations_user_id;
DROP INDEX IF EXISTS public.ix_github_user_installations_platform_app_id;
DROP INDEX IF EXISTS public.ix_git_worktree_path_claims_root_session_id;
DROP INDEX IF EXISTS public.ix_git_worktree_path_claims_agent_runtime_id;
DROP INDEX IF EXISTS public.ix_git_worktree_path_claims_action_execution_id;
DROP INDEX IF EXISTS public.ix_external_channel_setup_claims_status_expires_at;
DROP INDEX IF EXISTS public.ix_external_channel_setup_claims_route_id_status;
DROP INDEX IF EXISTS public.ix_external_channel_resources_latest_activity_at;
DROP INDEX IF EXISTS public.ix_external_channel_resources_connection_id_status;
DROP INDEX IF EXISTS public.ix_external_channel_participation_settings_route_id_status;
DROP INDEX IF EXISTS public.ix_external_channel_interactions_setup_claim_id;
DROP INDEX IF EXISTS public.ix_external_channel_interactions_expires_at;
DROP INDEX IF EXISTS public.ix_external_channel_ingress_owners_recovery;
DROP INDEX IF EXISTS public.ix_external_channel_ingress_leases_lease_until;
DROP INDEX IF EXISTS public.ix_external_channel_ingress_items_position;
DROP INDEX IF EXISTS public.ix_external_channel_ingress_items_owner_due_queue;
DROP INDEX IF EXISTS public.ix_external_channel_connections_workspace_id;
DROP INDEX IF EXISTS public.ix_external_channel_connections_status;
DROP INDEX IF EXISTS public.ix_external_channel_connections_socket_lease_until;
DROP INDEX IF EXISTS public.ix_external_channel_connections_slack_presence_lease_until;
DROP INDEX IF EXISTS public.ix_external_channel_channel_defaults_route_id_status;
DROP INDEX IF EXISTS public.ix_external_channel_bindings_route_id;
DROP INDEX IF EXISTS public.ix_external_channel_bindings_agent_session_id;
DROP INDEX IF EXISTS public.ix_external_channel_app_claims_connection_id;
DROP INDEX IF EXISTS public.ix_external_channel_agent_routes_connection_id;
DROP INDEX IF EXISTS public.ix_external_channel_agent_routes_agent_id;
DROP INDEX IF EXISTS public.ix_external_channel_access_requests_status_created_at;
DROP INDEX IF EXISTS public.ix_external_channel_access_requests_setup_claim_id;
DROP INDEX IF EXISTS public.ix_external_channel_access_requests_agent_session_id;
DROP INDEX IF EXISTS public.ix_external_channel_access_grants_agent_session_id;
DROP INDEX IF EXISTS public.ix_external_channel_access_grants_agent_id;
DROP INDEX IF EXISTS public.ix_exchange_files_workspace_id;
DROP INDEX IF EXISTS public.ix_exchange_files_status_expires_at;
DROP INDEX IF EXISTS public.ix_exchange_files_retention_root_status;
DROP INDEX IF EXISTS public.ix_exchange_files_preview_thumbnail_file_id;
DROP INDEX IF EXISTS public.ix_exchange_files_origin_type;
DROP INDEX IF EXISTS public.ix_events_session_id;
DROP INDEX IF EXISTS public.ix_events_session_created;
DROP INDEX IF EXISTS public.ix_chatgpt_oauth_sessions_workspace_id;
DROP INDEX IF EXISTS public.ix_chatgpt_oauth_sessions_user_id;
DROP INDEX IF EXISTS public.ix_chatgpt_oauth_sessions_state;
DROP INDEX IF EXISTS public.ix_chat_write_requests_session_id;
DROP INDEX IF EXISTS public.ix_artifacts_workspace_id;
DROP INDEX IF EXISTS public.ix_artifacts_status_expires_at;
DROP INDEX IF EXISTS public.ix_artifacts_session_status;
DROP INDEX IF EXISTS public.ix_archived_session_retention_applications_status_created_at;
DROP INDEX IF EXISTS public.ix_archived_session_retention_applications_lease_until;
DROP INDEX IF EXISTS public.ix_archived_session_purge_jobs_status_eligible_at;
DROP INDEX IF EXISTS public.ix_archived_session_purge_jobs_lease_until;
DROP INDEX IF EXISTS public.ix_archived_purge_part_exec_job_phase;
DROP INDEX IF EXISTS public.ix_agents_workspace_id;
DROP INDEX IF EXISTS public.ix_agents_runtime_profile_id;
DROP INDEX IF EXISTS public.ix_agent_toolkits_agent_id;
DROP INDEX IF EXISTS public.ix_agent_sessions_workspace_id;
DROP INDEX IF EXISTS public.ix_agent_sessions_stop_requested_at;
DROP INDEX IF EXISTS public.ix_agent_sessions_session_kind;
DROP INDEX IF EXISTS public.ix_agent_sessions_run_state_running;
DROP INDEX IF EXISTS public.ix_agent_sessions_pending_command;
DROP INDEX IF EXISTS public.ix_agent_sessions_model_input_head_event_id;
DROP INDEX IF EXISTS public.ix_agent_sessions_model_file_gc_cursor;
DROP INDEX IF EXISTS public.ix_agent_sessions_associated_user_id;
DROP INDEX IF EXISTS public.ix_agent_sessions_archived_purge_after;
DROP INDEX IF EXISTS public.ix_agent_sessions_agent_id;
DROP INDEX IF EXISTS public.ix_agent_sessions_agent_associated_user_status;
DROP INDEX IF EXISTS public.ix_agent_sessions_agent_active_last_user_input;
DROP INDEX IF EXISTS public.ix_agent_sessions_active_auto_archive;
DROP INDEX IF EXISTS public.ix_agent_runtimes_workspace_id;
DROP INDEX IF EXISTS public.ix_agent_runtimes_runtime_provider_resource_id;
DROP INDEX IF EXISTS public.ix_agent_runtimes_runtime_provider_id;
DROP INDEX IF EXISTS public.ix_agent_runtimes_runner_state;
DROP INDEX IF EXISTS public.ix_agent_runtimes_provider_observe_requested_at;
DROP INDEX IF EXISTS public.ix_agent_runtimes_provider_connection_state;
DROP INDEX IF EXISTS public.ix_agent_runtimes_lifecycle_dispatch;
DROP INDEX IF EXISTS public.ix_agent_runtimes_desired_observed;
DROP INDEX IF EXISTS public.ix_agent_runtime_removal_operations_status_next_attempt_at;
DROP INDEX IF EXISTS public.ix_agent_runtime_removal_operations_agent_created_at;
DROP INDEX IF EXISTS public.ix_agent_runtime_add_receipts_agent_created_at;
DROP INDEX IF EXISTS public.ix_agent_runs_status;
DROP INDEX IF EXISTS public.ix_agent_runs_session_status;
DROP INDEX IF EXISTS public.ix_agent_runs_session_id;
DROP INDEX IF EXISTS public.ix_agent_runs_phase;
DROP INDEX IF EXISTS public.ix_agent_runs_parent_agent_run_id;
DROP INDEX IF EXISTS public.ix_agent_run_input_events_run_input_order;
DROP INDEX IF EXISTS public.ix_agent_run_input_events_event_run;
DROP INDEX IF EXISTS public.ix_agent_project_presets_agent_updated;
DROP INDEX IF EXISTS public.ix_agent_project_defaults_agent_position;
DROP INDEX IF EXISTS public.ix_agent_project_catalog_entries_agent_updated;
DROP INDEX IF EXISTS public.ix_agent_memories_agent_user;
DROP INDEX IF EXISTS public.ix_agent_memories_agent_id;
DROP INDEX IF EXISTS public.ix_agent_decommission_jobs_status_next_attempt_at;
DROP INDEX IF EXISTS public.ix_agent_avatar_cleanup_jobs_next_attempt_lease_until;
DROP INDEX IF EXISTS public.ix_agent_avatar_cleanup_jobs_agent_id;
DROP INDEX IF EXISTS public.ix_agent_automatic_project_items_agent_position;
DROP INDEX IF EXISTS public.ix_agent_admins_workspace_user_id;
DROP INDEX IF EXISTS public.ix_agent_admins_agent_id;
DROP INDEX IF EXISTS public.ix_action_executions_session_id_status;
DROP INDEX IF EXISTS public.ix_action_executions_session_id_mailbox_item_id;
DROP INDEX IF EXISTS public.ix_action_executions_session_id;
DROP INDEX IF EXISTS public.ix_action_execution_events_session_id;
DROP INDEX IF EXISTS public.ix_action_execution_events_action_execution_id;
ALTER TABLE IF EXISTS ONLY public.xai_oauth_sessions DROP CONSTRAINT IF EXISTS xai_oauth_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.workspaces DROP CONSTRAINT IF EXISTS workspaces_pkey;
ALTER TABLE IF EXISTS ONLY public.workspace_users DROP CONSTRAINT IF EXISTS workspace_users_pkey;
ALTER TABLE IF EXISTS ONLY public.workspace_runtime_profiles DROP CONSTRAINT IF EXISTS workspace_runtime_profiles_pkey;
ALTER TABLE IF EXISTS ONLY public.workspace_model_settings DROP CONSTRAINT IF EXISTS workspace_model_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.workspace_join_requests DROP CONSTRAINT IF EXISTS workspace_join_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.workspace_invitations DROP CONSTRAINT IF EXISTS workspace_invitations_pkey;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE IF EXISTS ONLY public.user_emails DROP CONSTRAINT IF EXISTS user_emails_pkey;
ALTER TABLE IF EXISTS ONLY public.workspaces DROP CONSTRAINT IF EXISTS uq_workspaces_handle;
ALTER TABLE IF EXISTS ONLY public.workspace_users DROP CONSTRAINT IF EXISTS uq_workspace_users_workspace_user;
ALTER TABLE IF EXISTS ONLY public.workspace_runtime_profiles DROP CONSTRAINT IF EXISTS uq_workspace_runtime_profiles_name;
ALTER TABLE IF EXISTS ONLY public.workspace_join_requests DROP CONSTRAINT IF EXISTS uq_workspace_join_requests_workspace_user;
ALTER TABLE IF EXISTS ONLY public.workspace_invitations DROP CONSTRAINT IF EXISTS uq_workspace_invitations_workspace_email;
ALTER TABLE IF EXISTS ONLY public.user_emails DROP CONSTRAINT IF EXISTS uq_user_emails_email;
ALTER TABLE IF EXISTS ONLY public.toolkit_states DROP CONSTRAINT IF EXISTS uq_toolkit_states_identity;
ALTER TABLE IF EXISTS ONLY public.toolkit_scopes DROP CONSTRAINT IF EXISTS uq_toolkit_scopes_toolkit_scope_id;
ALTER TABLE IF EXISTS ONLY public.system_setting_candidates DROP CONSTRAINT IF EXISTS uq_system_setting_candidates_section;
ALTER TABLE IF EXISTS ONLY public.signup_tokens DROP CONSTRAINT IF EXISTS uq_signup_tokens_token_hash;
ALTER TABLE IF EXISTS ONLY public.sessions DROP CONSTRAINT IF EXISTS uq_sessions_refresh_token;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS uq_session_agents_root_path;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS uq_session_agents_parent_name;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS uq_session_agents_agent_session_id;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS uq_session_agent_contexts_working_folder_path;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS uq_session_agent_contexts_root_session_agent_id;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_projects DROP CONSTRAINT IF EXISTS uq_session_agent_context_projects_context_path;
ALTER TABLE IF EXISTS ONLY public.sandbox_runtime_leases DROP CONSTRAINT IF EXISTS uq_sandbox_runtime_leases_runtime_generation;
ALTER TABLE IF EXISTS ONLY public.sandbox_checkpoints DROP CONSTRAINT IF EXISTS uq_sandbox_checkpoints_object_key;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operation_items DROP CONSTRAINT IF EXISTS uq_runtime_recreation_operation_items_operation_runtime;
ALTER TABLE IF EXISTS ONLY public.runtime_providers DROP CONSTRAINT IF EXISTS uq_runtime_providers_provider_id;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_connections DROP CONSTRAINT IF EXISTS uq_runtime_provider_connections_provider_generation;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_connections DROP CONSTRAINT IF EXISTS uq_runtime_provider_connections_connection_id;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS uq_runtime_provider_config_revisions_provider_revision;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_sources DROP CONSTRAINT IF EXISTS uq_runtime_provider_bootstrap_sources_source_key;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_declarations DROP CONSTRAINT IF EXISTS uq_runtime_provider_bootstrap_declarations_source_key;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_declarations DROP CONSTRAINT IF EXISTS uq_runtime_provider_bootstrap_declarations_provider_id;
ALTER TABLE IF EXISTS ONLY public.runtime_infrastructure_profiles DROP CONSTRAINT IF EXISTS uq_runtime_infrastructure_profiles_provider_name;
ALTER TABLE IF EXISTS ONLY public.runtime_infrastructure_profiles DROP CONSTRAINT IF EXISTS uq_runtime_infrastructure_profiles_provider_id;
ALTER TABLE IF EXISTS ONLY public.runtime_configuration_reconcile_tasks DROP CONSTRAINT IF EXISTS uq_runtime_configuration_reconcile_tasks_source_version;
ALTER TABLE IF EXISTS ONLY public.password_reset_tokens DROP CONSTRAINT IF EXISTS uq_password_reset_tokens_token_hash;
ALTER TABLE IF EXISTS ONLY public.password_logins DROP CONSTRAINT IF EXISTS uq_password_logins_user_id;
ALTER TABLE IF EXISTS ONLY public.model_files DROP CONSTRAINT IF EXISTS uq_model_files_storage_key;
ALTER TABLE IF EXISTS ONLY public.model_file_pins DROP CONSTRAINT IF EXISTS uq_model_file_pins_model_file_run;
ALTER TABLE IF EXISTS ONLY public.mcp_oauth_connections DROP CONSTRAINT IF EXISTS uq_mcp_oauth_connections_toolkit_id;
ALTER TABLE IF EXISTS ONLY public.litellm_source_snapshots DROP CONSTRAINT IF EXISTS uq_litellm_source_snapshots_source_hash;
ALTER TABLE IF EXISTS ONLY public.git_worktree_path_claims DROP CONSTRAINT IF EXISTS uq_git_worktree_path_claims_agent_runtime_path;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS uq_external_channel_setup_claims_connection_id_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_resources DROP CONSTRAINT IF EXISTS uq_external_channel_resources_connection_type_provider_key;
ALTER TABLE IF EXISTS ONLY public.external_channel_resources DROP CONSTRAINT IF EXISTS uq_external_channel_resources_connection_id_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_principals DROP CONSTRAINT IF EXISTS uq_external_channel_principals_provider_tenant_user;
ALTER TABLE IF EXISTS ONLY public.external_channel_participation_settings DROP CONSTRAINT IF EXISTS uq_external_channel_participation_settings_connection_id_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_interactions DROP CONSTRAINT IF EXISTS uq_external_channel_interactions_connection_provider_key;
ALTER TABLE IF EXISTS ONLY public.external_channel_interactions DROP CONSTRAINT IF EXISTS uq_external_channel_interactions_connection_id_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS uq_external_channel_ingress_owners_target_resource;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_leases DROP CONSTRAINT IF EXISTS uq_external_channel_ingress_leases_connection_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS uq_external_channel_ingress_items_queue_key;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS uq_external_channel_ingress_items_active_identity;
ALTER TABLE IF EXISTS ONLY public.external_channel_conversation_positions DROP CONSTRAINT IF EXISTS uq_external_channel_conversation_positions_connection_id_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_connections DROP CONSTRAINT IF EXISTS uq_external_channel_connections_id_app_mode;
ALTER TABLE IF EXISTS ONLY public.external_channel_blocks DROP CONSTRAINT IF EXISTS uq_external_channel_blocks_agent_principal;
ALTER TABLE IF EXISTS ONLY public.external_channel_app_claims DROP CONSTRAINT IF EXISTS uq_external_channel_app_claims_provider_app_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_routes DROP CONSTRAINT IF EXISTS uq_external_channel_agent_routes_connection_id_id;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_routes DROP CONSTRAINT IF EXISTS uq_external_channel_agent_routes_connection_agent;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS uq_external_channel_access_requests_route_trigger_message;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS uq_exchange_files_object_key;
ALTER TABLE IF EXISTS ONLY public.chat_write_requests DROP CONSTRAINT IF EXISTS uq_chat_write_requests_session_requester_client_request;
ALTER TABLE IF EXISTS ONLY public.artifacts DROP CONSTRAINT IF EXISTS uq_artifacts_storage_key;
ALTER TABLE IF EXISTS ONLY public.archived_session_purge_jobs DROP CONSTRAINT IF EXISTS uq_archived_session_purge_jobs_root_session_id;
ALTER TABLE IF EXISTS ONLY public.agent_toolkits DROP CONSTRAINT IF EXISTS uq_agent_toolkits_agent_toolkit;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS uq_agent_sessions_handle;
ALTER TABLE IF EXISTS ONLY public.agent_session_unread_runs DROP CONSTRAINT IF EXISTS uq_agent_session_unread_runs_run_id;
ALTER TABLE IF EXISTS ONLY public.agent_runtimes DROP CONSTRAINT IF EXISTS uq_agent_runtimes_id_workspace_id;
ALTER TABLE IF EXISTS ONLY public.agent_runtimes DROP CONSTRAINT IF EXISTS uq_agent_runtimes_agent_id;
ALTER TABLE IF EXISTS ONLY public.agent_runs DROP CONSTRAINT IF EXISTS uq_agent_runs_session_run_index;
ALTER TABLE IF EXISTS ONLY public.agent_run_input_events DROP CONSTRAINT IF EXISTS uq_agent_run_input_events_run_input_order;
ALTER TABLE IF EXISTS ONLY public.agent_project_presets DROP CONSTRAINT IF EXISTS uq_agent_project_presets_agent_path;
ALTER TABLE IF EXISTS ONLY public.agent_project_defaults DROP CONSTRAINT IF EXISTS uq_agent_project_defaults_agent_position;
ALTER TABLE IF EXISTS ONLY public.agent_project_catalog_entries DROP CONSTRAINT IF EXISTS uq_agent_project_catalog_entries_agent_path;
ALTER TABLE IF EXISTS ONLY public.agent_decommission_jobs DROP CONSTRAINT IF EXISTS uq_agent_decommission_jobs_agent_id;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_items DROP CONSTRAINT IF EXISTS uq_agent_automatic_project_items_agent_position;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_items DROP CONSTRAINT IF EXISTS uq_agent_automatic_project_items_agent_path;
ALTER TABLE IF EXISTS ONLY public.agent_admins DROP CONSTRAINT IF EXISTS uq_agent_admins_agent_workspace_user;
ALTER TABLE IF EXISTS ONLY public.action_executions DROP CONSTRAINT IF EXISTS uq_action_executions_mailbox_item_id;
ALTER TABLE IF EXISTS ONLY public.action_execution_events DROP CONSTRAINT IF EXISTS uq_action_execution_events_execution_sequence;
ALTER TABLE IF EXISTS ONLY public.toolkit_configs DROP CONSTRAINT IF EXISTS toolkits_pkey;
ALTER TABLE IF EXISTS ONLY public.toolkit_states DROP CONSTRAINT IF EXISTS toolkit_states_pkey;
ALTER TABLE IF EXISTS ONLY public.toolkit_scopes DROP CONSTRAINT IF EXISTS toolkit_scopes_pkey;
ALTER TABLE IF EXISTS ONLY public.system_user_roles DROP CONSTRAINT IF EXISTS system_user_roles_pkey;
ALTER TABLE IF EXISTS ONLY public.system_settings DROP CONSTRAINT IF EXISTS system_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.system_setting_health DROP CONSTRAINT IF EXISTS system_setting_health_pkey;
ALTER TABLE IF EXISTS ONLY public.system_setting_candidates DROP CONSTRAINT IF EXISTS system_setting_candidates_pkey;
ALTER TABLE IF EXISTS ONLY public.system_setting_audit_events DROP CONSTRAINT IF EXISTS system_setting_audit_events_pkey;
ALTER TABLE IF EXISTS ONLY public.system_file_lifecycle_settings DROP CONSTRAINT IF EXISTS system_file_lifecycle_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.system_data_migrations DROP CONSTRAINT IF EXISTS system_data_migrations_pkey;
ALTER TABLE IF EXISTS ONLY public.system_bootstrap_states DROP CONSTRAINT IF EXISTS system_bootstrap_states_pkey;
ALTER TABLE IF EXISTS ONLY public.signup_tokens DROP CONSTRAINT IF EXISTS signup_tokens_pkey;
ALTER TABLE IF EXISTS ONLY public.signup_token_redemptions DROP CONSTRAINT IF EXISTS signup_token_redemptions_pkey;
ALTER TABLE IF EXISTS ONLY public.sessions DROP CONSTRAINT IF EXISTS sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.kubernetes_sandbox_snapshots DROP CONSTRAINT IF EXISTS session_snapshots_pkey;
ALTER TABLE IF EXISTS ONLY public.session_agents DROP CONSTRAINT IF EXISTS session_agents_pkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_contexts DROP CONSTRAINT IF EXISTS session_agent_contexts_pkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_projects DROP CONSTRAINT IF EXISTS session_agent_context_projects_pkey;
ALTER TABLE IF EXISTS ONLY public.session_agent_context_git_worktrees DROP CONSTRAINT IF EXISTS session_agent_context_git_worktrees_pkey;
ALTER TABLE IF EXISTS ONLY public.scheduled_tasks DROP CONSTRAINT IF EXISTS scheduled_tasks_pkey;
ALTER TABLE IF EXISTS ONLY public.scheduled_task_states DROP CONSTRAINT IF EXISTS scheduled_task_states_pkey;
ALTER TABLE IF EXISTS ONLY public.sandbox_runtime_leases DROP CONSTRAINT IF EXISTS sandbox_runtime_leases_pkey;
ALTER TABLE IF EXISTS ONLY public.sandbox_checkpoints DROP CONSTRAINT IF EXISTS sandbox_checkpoints_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operations DROP CONSTRAINT IF EXISTS runtime_recreation_operations_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_recreation_operation_items DROP CONSTRAINT IF EXISTS runtime_recreation_operation_items_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_providers DROP CONSTRAINT IF EXISTS runtime_providers_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_workspace_availability DROP CONSTRAINT IF EXISTS runtime_provider_workspace_availability_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_enrollment_grants DROP CONSTRAINT IF EXISTS runtime_provider_enrollment_grants_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_credentials DROP CONSTRAINT IF EXISTS runtime_provider_credentials_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_contract_revisions DROP CONSTRAINT IF EXISTS runtime_provider_contract_revisions_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_connections DROP CONSTRAINT IF EXISTS runtime_provider_connections_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_config_revisions DROP CONSTRAINT IF EXISTS runtime_provider_config_revisions_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_sources DROP CONSTRAINT IF EXISTS runtime_provider_bootstrap_sources_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_bootstrap_declarations DROP CONSTRAINT IF EXISTS runtime_provider_bootstrap_declarations_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_bindings DROP CONSTRAINT IF EXISTS runtime_provider_auth_bindings_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_auth_binding_audit_events DROP CONSTRAINT IF EXISTS runtime_provider_auth_binding_audit_events_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_provider_audit_events DROP CONSTRAINT IF EXISTS runtime_provider_audit_events_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_infrastructure_profiles DROP CONSTRAINT IF EXISTS runtime_infrastructure_profiles_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_connection_generations DROP CONSTRAINT IF EXISTS runtime_connection_generations_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_connection_generation_cutovers DROP CONSTRAINT IF EXISTS runtime_connection_generation_cutovers_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_configuration_states DROP CONSTRAINT IF EXISTS runtime_configuration_states_pkey;
ALTER TABLE IF EXISTS ONLY public.runtime_configuration_reconcile_tasks DROP CONSTRAINT IF EXISTS runtime_configuration_reconcile_tasks_pkey;
ALTER TABLE IF EXISTS ONLY public.mailbox_items DROP CONSTRAINT IF EXISTS pk_mailbox_items;
ALTER TABLE IF EXISTS ONLY public.events DROP CONSTRAINT IF EXISTS pk_events;
ALTER TABLE IF EXISTS ONLY public.agent_sessions DROP CONSTRAINT IF EXISTS pk_agent_sessions;
ALTER TABLE IF EXISTS ONLY public.agent_runs DROP CONSTRAINT IF EXISTS pk_agent_runs;
ALTER TABLE IF EXISTS ONLY public.password_reset_tokens DROP CONSTRAINT IF EXISTS password_reset_tokens_pkey;
ALTER TABLE IF EXISTS ONLY public.password_reset_token_redemptions DROP CONSTRAINT IF EXISTS password_reset_token_redemptions_pkey;
ALTER TABLE IF EXISTS ONLY public.password_logins DROP CONSTRAINT IF EXISTS password_logins_pkey;
ALTER TABLE IF EXISTS ONLY public.owner_lifecycle_jobs DROP CONSTRAINT IF EXISTS owner_lifecycle_jobs_pkey;
ALTER TABLE IF EXISTS ONLY public.model_files DROP CONSTRAINT IF EXISTS model_files_pkey;
ALTER TABLE IF EXISTS ONLY public.mcp_oauth_connections DROP CONSTRAINT IF EXISTS mcp_oauth_connections_pkey;
ALTER TABLE IF EXISTS ONLY public.llm_provider_integrations DROP CONSTRAINT IF EXISTS llm_provider_integrations_pkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalogs DROP CONSTRAINT IF EXISTS llm_catalogs_pkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_sync_attempts DROP CONSTRAINT IF EXISTS llm_catalog_sync_attempts_pkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_snapshots DROP CONSTRAINT IF EXISTS llm_catalog_snapshots_pkey;
ALTER TABLE IF EXISTS ONLY public.llm_catalog_entries DROP CONSTRAINT IF EXISTS llm_catalog_entries_pkey;
ALTER TABLE IF EXISTS ONLY public.litellm_source_snapshots DROP CONSTRAINT IF EXISTS litellm_source_snapshots_pkey;
ALTER TABLE IF EXISTS ONLY public.kimi_oauth_sessions DROP CONSTRAINT IF EXISTS kimi_oauth_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.github_user_installations DROP CONSTRAINT IF EXISTS github_user_installations_pkey;
ALTER TABLE IF EXISTS ONLY public.git_worktree_path_claims DROP CONSTRAINT IF EXISTS git_worktree_path_claims_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_setup_claims DROP CONSTRAINT IF EXISTS external_channel_setup_claims_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_resources DROP CONSTRAINT IF EXISTS external_channel_resources_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_principals DROP CONSTRAINT IF EXISTS external_channel_principals_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_participation_settings DROP CONSTRAINT IF EXISTS external_channel_participation_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_interactions DROP CONSTRAINT IF EXISTS external_channel_interactions_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_owners DROP CONSTRAINT IF EXISTS external_channel_ingress_owners_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_leases DROP CONSTRAINT IF EXISTS external_channel_ingress_leases_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_ingress_items DROP CONSTRAINT IF EXISTS external_channel_ingress_items_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_conversation_positions DROP CONSTRAINT IF EXISTS external_channel_conversation_positions_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_connections DROP CONSTRAINT IF EXISTS external_channel_connections_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_channel_defaults DROP CONSTRAINT IF EXISTS external_channel_channel_defaults_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_blocks DROP CONSTRAINT IF EXISTS external_channel_blocks_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_bindings DROP CONSTRAINT IF EXISTS external_channel_bindings_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_app_claims DROP CONSTRAINT IF EXISTS external_channel_app_claims_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_routes DROP CONSTRAINT IF EXISTS external_channel_agent_routes_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_agent_route_bot_policy_archive DROP CONSTRAINT IF EXISTS external_channel_agent_route_bot_policy_archive_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_requests DROP CONSTRAINT IF EXISTS external_channel_access_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.external_channel_access_grants DROP CONSTRAINT IF EXISTS external_channel_access_grants_pkey;
ALTER TABLE IF EXISTS ONLY public.exchange_files DROP CONSTRAINT IF EXISTS exchange_files_pkey;
ALTER TABLE IF EXISTS ONLY public.email_verifications DROP CONSTRAINT IF EXISTS email_verifications_pkey;
ALTER TABLE IF EXISTS ONLY public.chatgpt_oauth_sessions DROP CONSTRAINT IF EXISTS chatgpt_oauth_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.chat_write_requests DROP CONSTRAINT IF EXISTS chat_write_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.artifacts DROP CONSTRAINT IF EXISTS artifacts_pkey;
ALTER TABLE IF EXISTS ONLY public.archived_session_retention_applications DROP CONSTRAINT IF EXISTS archived_session_retention_applications_pkey;
ALTER TABLE IF EXISTS ONLY public.archived_session_purge_participant_executions DROP CONSTRAINT IF EXISTS archived_session_purge_participant_executions_pkey;
ALTER TABLE IF EXISTS ONLY public.archived_session_purge_jobs DROP CONSTRAINT IF EXISTS archived_session_purge_jobs_pkey;
ALTER TABLE IF EXISTS ONLY public.agents DROP CONSTRAINT IF EXISTS agents_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_toolkits DROP CONSTRAINT IF EXISTS agent_toolkits_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_session_unread_runs DROP CONSTRAINT IF EXISTS agent_session_unread_runs_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_session_system_prompt_snapshots DROP CONSTRAINT IF EXISTS agent_session_system_prompt_snapshots_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtimes DROP CONSTRAINT IF EXISTS agent_runtimes_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_removal_operations DROP CONSTRAINT IF EXISTS agent_runtime_removal_operations_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_runtime_add_receipts DROP CONSTRAINT IF EXISTS agent_runtime_add_receipts_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_run_input_events DROP CONSTRAINT IF EXISTS agent_run_input_events_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_project_presets DROP CONSTRAINT IF EXISTS agent_project_presets_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_project_defaults DROP CONSTRAINT IF EXISTS agent_project_defaults_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_project_catalog_entries DROP CONSTRAINT IF EXISTS agent_project_catalog_entries_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_memories DROP CONSTRAINT IF EXISTS agent_memories_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_decommission_jobs DROP CONSTRAINT IF EXISTS agent_decommission_jobs_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_avatar_cleanup_jobs DROP CONSTRAINT IF EXISTS agent_avatar_cleanup_jobs_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_settings DROP CONSTRAINT IF EXISTS agent_automatic_project_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_automatic_project_items DROP CONSTRAINT IF EXISTS agent_automatic_project_items_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_admins DROP CONSTRAINT IF EXISTS agent_admins_pkey;
ALTER TABLE IF EXISTS ONLY public.action_executions DROP CONSTRAINT IF EXISTS action_executions_pkey;
ALTER TABLE IF EXISTS ONLY public.action_execution_events DROP CONSTRAINT IF EXISTS action_execution_events_pkey;
ALTER TABLE IF EXISTS public.system_bootstrap_states ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.runtime_connection_generation_cutovers ALTER COLUMN allocator_version DROP DEFAULT;
DROP TABLE IF EXISTS public.xai_oauth_sessions;
DROP TABLE IF EXISTS public.workspaces;
DROP TABLE IF EXISTS public.workspace_users;
DROP TABLE IF EXISTS public.workspace_runtime_profiles;
DROP TABLE IF EXISTS public.workspace_model_settings;
DROP TABLE IF EXISTS public.workspace_join_requests;
DROP TABLE IF EXISTS public.workspace_invitations;
DROP TABLE IF EXISTS public.users;
DROP TABLE IF EXISTS public.user_emails;
DROP TABLE IF EXISTS public.toolkit_states;
DROP TABLE IF EXISTS public.toolkit_scopes;
DROP TABLE IF EXISTS public.toolkit_configs;
DROP TABLE IF EXISTS public.system_user_roles;
DROP TABLE IF EXISTS public.system_settings;
DROP TABLE IF EXISTS public.system_setting_health;
DROP TABLE IF EXISTS public.system_setting_candidates;
DROP TABLE IF EXISTS public.system_setting_audit_events;
DROP TABLE IF EXISTS public.system_file_lifecycle_settings;
DROP TABLE IF EXISTS public.system_data_migrations;
DROP SEQUENCE IF EXISTS public.system_bootstrap_states_id_seq;
DROP TABLE IF EXISTS public.system_bootstrap_states;
DROP TABLE IF EXISTS public.signup_tokens;
DROP TABLE IF EXISTS public.signup_token_redemptions;
DROP TABLE IF EXISTS public.sessions;
DROP TABLE IF EXISTS public.session_agents;
DROP TABLE IF EXISTS public.session_agent_contexts;
DROP TABLE IF EXISTS public.session_agent_context_projects;
DROP TABLE IF EXISTS public.session_agent_context_git_worktrees;
DROP TABLE IF EXISTS public.scheduled_tasks;
DROP TABLE IF EXISTS public.scheduled_task_states;
DROP TABLE IF EXISTS public.sandbox_runtime_leases;
DROP TABLE IF EXISTS public.sandbox_checkpoints;
DROP TABLE IF EXISTS public.runtime_recreation_operations;
DROP TABLE IF EXISTS public.runtime_recreation_operation_items;
DROP TABLE IF EXISTS public.runtime_providers;
DROP TABLE IF EXISTS public.runtime_provider_workspace_availability;
DROP TABLE IF EXISTS public.runtime_provider_enrollment_grants;
DROP TABLE IF EXISTS public.runtime_provider_credentials;
DROP TABLE IF EXISTS public.runtime_provider_contract_revisions;
DROP TABLE IF EXISTS public.runtime_provider_connections;
DROP TABLE IF EXISTS public.runtime_provider_config_revisions;
DROP TABLE IF EXISTS public.runtime_provider_bootstrap_sources;
DROP TABLE IF EXISTS public.runtime_provider_bootstrap_declarations;
DROP TABLE IF EXISTS public.runtime_provider_auth_bindings;
DROP TABLE IF EXISTS public.runtime_provider_auth_binding_audit_events;
DROP TABLE IF EXISTS public.runtime_provider_audit_events;
DROP TABLE IF EXISTS public.runtime_infrastructure_profiles;
DROP TABLE IF EXISTS public.runtime_connection_generations;
DROP SEQUENCE IF EXISTS public.runtime_connection_generation_cutovers_allocator_version_seq;
DROP TABLE IF EXISTS public.runtime_connection_generation_cutovers;
DROP TABLE IF EXISTS public.runtime_configuration_states;
DROP TABLE IF EXISTS public.runtime_configuration_reconcile_tasks;
DROP TABLE IF EXISTS public.password_reset_tokens;
DROP TABLE IF EXISTS public.password_reset_token_redemptions;
DROP TABLE IF EXISTS public.password_logins;
DROP TABLE IF EXISTS public.owner_lifecycle_jobs;
DROP TABLE IF EXISTS public.model_files;
DROP TABLE IF EXISTS public.model_file_pins;
DROP TABLE IF EXISTS public.mcp_oauth_connections;
DROP TABLE IF EXISTS public.mailbox_items;
DROP TABLE IF EXISTS public.llm_provider_integrations;
DROP TABLE IF EXISTS public.llm_catalogs;
DROP TABLE IF EXISTS public.llm_catalog_sync_attempts;
DROP TABLE IF EXISTS public.llm_catalog_snapshots;
DROP TABLE IF EXISTS public.llm_catalog_entries;
DROP TABLE IF EXISTS public.litellm_source_snapshots;
DROP TABLE IF EXISTS public.kubernetes_sandbox_snapshots;
DROP TABLE IF EXISTS public.kimi_oauth_sessions;
DROP TABLE IF EXISTS public.github_user_installations;
DROP TABLE IF EXISTS public.git_worktree_path_claims;
DROP TABLE IF EXISTS public.external_channel_setup_claims;
DROP TABLE IF EXISTS public.external_channel_resources;
DROP TABLE IF EXISTS public.external_channel_principals;
DROP TABLE IF EXISTS public.external_channel_participation_settings;
DROP TABLE IF EXISTS public.external_channel_interactions;
DROP TABLE IF EXISTS public.external_channel_ingress_owners;
DROP TABLE IF EXISTS public.external_channel_ingress_leases;
DROP TABLE IF EXISTS public.external_channel_ingress_items;
DROP TABLE IF EXISTS public.external_channel_conversation_positions;
DROP TABLE IF EXISTS public.external_channel_connections;
DROP TABLE IF EXISTS public.external_channel_channel_defaults;
DROP TABLE IF EXISTS public.external_channel_blocks;
DROP TABLE IF EXISTS public.external_channel_bindings;
DROP TABLE IF EXISTS public.external_channel_app_claims;
DROP TABLE IF EXISTS public.external_channel_agent_routes;
DROP TABLE IF EXISTS public.external_channel_agent_route_bot_policy_archive;
DROP TABLE IF EXISTS public.external_channel_access_requests;
DROP TABLE IF EXISTS public.external_channel_access_grants;
DROP TABLE IF EXISTS public.exchange_files;
DROP TABLE IF EXISTS public.events;
DROP TABLE IF EXISTS public.email_verifications;
DROP TABLE IF EXISTS public.chatgpt_oauth_sessions;
DROP TABLE IF EXISTS public.chat_write_requests;
DROP TABLE IF EXISTS public.artifacts;
DROP TABLE IF EXISTS public.archived_session_retention_applications;
DROP TABLE IF EXISTS public.archived_session_purge_participant_executions;
DROP TABLE IF EXISTS public.archived_session_purge_jobs;
DROP TABLE IF EXISTS public.agents;
DROP TABLE IF EXISTS public.agent_toolkits;
DROP TABLE IF EXISTS public.agent_sessions;
DROP TABLE IF EXISTS public.agent_session_unread_runs;
DROP TABLE IF EXISTS public.agent_session_system_prompt_snapshots;
DROP TABLE IF EXISTS public.agent_runtimes;
DROP TABLE IF EXISTS public.agent_runtime_removal_operations;
DROP TABLE IF EXISTS public.agent_runtime_add_receipts;
DROP TABLE IF EXISTS public.agent_runs;
DROP TABLE IF EXISTS public.agent_run_input_events;
DROP TABLE IF EXISTS public.agent_project_presets;
DROP TABLE IF EXISTS public.agent_project_defaults;
DROP TABLE IF EXISTS public.agent_project_catalog_entries;
DROP TABLE IF EXISTS public.agent_memories;
DROP TABLE IF EXISTS public.agent_decommission_jobs;
DROP TABLE IF EXISTS public.agent_avatar_cleanup_jobs;
DROP TABLE IF EXISTS public.agent_automatic_project_settings;
DROP TABLE IF EXISTS public.agent_automatic_project_items;
DROP TABLE IF EXISTS public.agent_admins;
DROP TABLE IF EXISTS public.action_executions;
DROP TABLE IF EXISTS public.action_execution_events;
DROP FUNCTION IF EXISTS public.prevent_external_channel_connection_app_mode_update();
DROP FUNCTION IF EXISTS public.preserve_external_channel_route_agent_snapshot();
DROP FUNCTION IF EXISTS public.initialize_runtime_provider_connection_generation();
DROP FUNCTION IF EXISTS public.initialize_agent_runtime_connection_generation();
DROP TYPE IF EXISTS public.xai_oauth_session_status;
DROP TYPE IF EXISTS public.xai_oauth_connection_method;
DROP TYPE IF EXISTS public.workspace_user_role;
DROP TYPE IF EXISTS public.toolkit_scope_type;
DROP TYPE IF EXISTS public.system_user_role;
DROP TYPE IF EXISTS public.system_setting_validation_status;
DROP TYPE IF EXISTS public.system_setting_section;
DROP TYPE IF EXISTS public.system_setting_health_status;
DROP TYPE IF EXISTS public.system_setting_audit_source;
DROP TYPE IF EXISTS public.system_setting_audit_event_type;
DROP TYPE IF EXISTS public.system_data_migration_outcome;
DROP TYPE IF EXISTS public.snapshot_kind;
DROP TYPE IF EXISTS public.signup_token_delivery_method;
DROP TYPE IF EXISTS public.session_working_folder_cleanup_status;
DROP TYPE IF EXISTS public.session_working_folder_binding_state;
DROP TYPE IF EXISTS public.session_git_worktree_status;
DROP TYPE IF EXISTS public.session_git_worktree_branch_created_by;
DROP TYPE IF EXISTS public.session_agent_kind;
DROP TYPE IF EXISTS public.scheduled_task_status;
DROP TYPE IF EXISTS public.scheduled_task_schedule_type;
DROP TYPE IF EXISTS public.schedule_type;
DROP TYPE IF EXISTS public.sandbox_runtime_lease_state;
DROP TYPE IF EXISTS public.sandbox_checkpoint_kind;
DROP TYPE IF EXISTS public.sandbox_checkpoint_format;
DROP TYPE IF EXISTS public.runtime_terminal_delete_acknowledgement_kind;
DROP TYPE IF EXISTS public.runtime_runner_state;
DROP TYPE IF EXISTS public.runtime_recreation_target_kind;
DROP TYPE IF EXISTS public.runtime_recreation_operation_status;
DROP TYPE IF EXISTS public.runtime_recreation_item_status;
DROP TYPE IF EXISTS public.runtime_reconcile_task_status;
DROP TYPE IF EXISTS public.runtime_reconcile_source_kind;
DROP TYPE IF EXISTS public.runtime_provider_scope;
DROP TYPE IF EXISTS public.runtime_provider_registration_method;
DROP TYPE IF EXISTS public.runtime_provider_observed_state;
DROP TYPE IF EXISTS public.runtime_provider_lifecycle_state;
DROP TYPE IF EXISTS public.runtime_provider_kind;
DROP TYPE IF EXISTS public.runtime_provider_enrollment_grant_state;
DROP TYPE IF EXISTS public.runtime_provider_credential_state;
DROP TYPE IF EXISTS public.runtime_provider_connection_status;
DROP TYPE IF EXISTS public.runtime_provider_connection_state;
DROP TYPE IF EXISTS public.runtime_provider_config_validation_status;
DROP TYPE IF EXISTS public.runtime_provider_config_revision_state;
DROP TYPE IF EXISTS public.runtime_provider_bootstrap_declaration_state;
DROP TYPE IF EXISTS public.runtime_provider_bootstrap_adapter_kind;
DROP TYPE IF EXISTS public.runtime_provider_binding_state;
DROP TYPE IF EXISTS public.runtime_provider_binding_owner;
DROP TYPE IF EXISTS public.runtime_provider_binding_origin;
DROP TYPE IF EXISTS public.runtime_provider_binding_audit_event_type;
DROP TYPE IF EXISTS public.runtime_provider_availability_mode;
DROP TYPE IF EXISTS public.runtime_provider_auth_method;
DROP TYPE IF EXISTS public.runtime_provider_audit_event_type;
DROP TYPE IF EXISTS public.runtime_profile_lifecycle;
DROP TYPE IF EXISTS public.runtime_lifecycle_command_type;
DROP TYPE IF EXISTS public.runtime_infrastructure_profile_kind;
DROP TYPE IF EXISTS public.runtime_desired_state;
DROP TYPE IF EXISTS public.runtime_connection_authority_kind;
DROP TYPE IF EXISTS public.runtime_configuration_state_status;
DROP TYPE IF EXISTS public.owner_lifecycle_status;
DROP TYPE IF EXISTS public.owner_lifecycle_kind;
DROP TYPE IF EXISTS public.model_reasoning_effort;
DROP TYPE IF EXISTS public.model_file_status;
DROP TYPE IF EXISTS public.memory_scope;
DROP TYPE IF EXISTS public.mcp_oauth_connection_status;
DROP TYPE IF EXISTS public.mailbox_item_scheduling_mode;
DROP TYPE IF EXISTS public.mailbox_item_kind;
DROP TYPE IF EXISTS public.llm_provider;
DROP TYPE IF EXISTS public.llm_model_lifecycle_status;
DROP TYPE IF EXISTS public.llm_catalog_scope;
DROP TYPE IF EXISTS public.llm_catalog_lowerer_target;
DROP TYPE IF EXISTS public.llm_catalog_entry_visibility;
DROP TYPE IF EXISTS public.llm_catalog_attempt_status;
DROP TYPE IF EXISTS public.kimi_oauth_session_status;
DROP TYPE IF EXISTS public.kimi_oauth_connection_method;
DROP TYPE IF EXISTS public.join_request_status;
DROP TYPE IF EXISTS public.invitation_status;
DROP TYPE IF EXISTS public.inference_profile_source;
DROP TYPE IF EXISTS public.inference_profile_failure_code;
DROP TYPE IF EXISTS public.git_worktree_path_claim_state;
DROP TYPE IF EXISTS public.git_worktree_path_claim_owner_kind;
DROP TYPE IF EXISTS public.external_channel_work_projection_status;
DROP TYPE IF EXISTS public.external_channel_transport;
DROP TYPE IF EXISTS public.external_channel_setup_claim_status;
DROP TYPE IF EXISTS public.external_channel_route_mode;
DROP TYPE IF EXISTS public.external_channel_route_catalog_status;
DROP TYPE IF EXISTS public.external_channel_response_mode;
DROP TYPE IF EXISTS public.external_channel_resource_type;
DROP TYPE IF EXISTS public.external_channel_resource_status;
DROP TYPE IF EXISTS public.external_channel_provider;
DROP TYPE IF EXISTS public.external_channel_principal_author_type;
DROP TYPE IF EXISTS public.external_channel_participation_setting_status;
DROP TYPE IF EXISTS public.external_channel_interaction_type;
DROP TYPE IF EXISTS public.external_channel_interaction_status;
DROP TYPE IF EXISTS public.external_channel_ingress_profile;
DROP TYPE IF EXISTS public.external_channel_ingress_item_state;
DROP TYPE IF EXISTS public.external_channel_ingress_authority_kind;
DROP TYPE IF EXISTS public.external_channel_conversation_scope_kind;
DROP TYPE IF EXISTS public.external_channel_conversation_location;
DROP TYPE IF EXISTS public.external_channel_connection_status;
DROP TYPE IF EXISTS public.external_channel_channel_default_status;
DROP TYPE IF EXISTS public.external_channel_app_mode;
DROP TYPE IF EXISTS public.external_channel_access_request_status;
DROP TYPE IF EXISTS public.external_channel_access_grant_scope;
DROP TYPE IF EXISTS public.exchange_file_status;
DROP TYPE IF EXISTS public.exchange_file_provenance_kind;
DROP TYPE IF EXISTS public.exchange_file_origin;
DROP TYPE IF EXISTS public.event_kind;
DROP TYPE IF EXISTS public.chatgpt_oauth_session_status;
DROP TYPE IF EXISTS public.chatgpt_oauth_connection_method;
DROP TYPE IF EXISTS public.chat_write_request_type;
DROP TYPE IF EXISTS public.artifact_status;
DROP TYPE IF EXISTS public.archived_session_retention_application_status;
DROP TYPE IF EXISTS public.archived_session_purge_status;
DROP TYPE IF EXISTS public.archived_session_purge_participant_phase;
DROP TYPE IF EXISTS public.agent_type;
DROP TYPE IF EXISTS public.agent_session_title_source;
DROP TYPE IF EXISTS public.agent_session_status;
DROP TYPE IF EXISTS public.agent_session_start_reason;
DROP TYPE IF EXISTS public.agent_session_run_state;
DROP TYPE IF EXISTS public.agent_session_product_mode;
DROP TYPE IF EXISTS public.agent_session_primary_kind;
DROP TYPE IF EXISTS public.agent_session_kind;
DROP TYPE IF EXISTS public.agent_session_end_reason;
DROP TYPE IF EXISTS public.agent_runtime_removal_status;
DROP TYPE IF EXISTS public.agent_runtime_removal_stage;
DROP TYPE IF EXISTS public.agent_runtime_capability;
DROP TYPE IF EXISTS public.agent_run_status;
DROP TYPE IF EXISTS public.agent_run_phase;
DROP TYPE IF EXISTS public.agent_run_parent_result_delivery_state;
DROP TYPE IF EXISTS public.agent_project_default_item_type;
DROP TYPE IF EXISTS public.agent_project_catalog_status;
DROP TYPE IF EXISTS public.agent_lifecycle_status;
DROP TYPE IF EXISTS public.agent_decommission_status;
DROP TYPE IF EXISTS public.action_execution_status;
DROP TYPE IF EXISTS public.action_execution_event_kind;
--
-- Name: action_execution_event_kind; Type: TYPE; Schema: public; Owner: -
--
"""


def upgrade() -> None:
    """Create the complete current Azents RDB schema."""
    op.get_bind().exec_driver_sql(_BASELINE_SQL)


def downgrade() -> None:
    """Remove every schema object created by the baseline."""
    op.get_bind().exec_driver_sql(_DOWNGRADE_SQL)
