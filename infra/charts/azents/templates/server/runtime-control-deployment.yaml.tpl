{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled }}
{{- $transfer := .Values.server.runtimeControl.transfer }}
{{- $webTransport := .Values.server.runtimeControl.webTransport }}
{{- $webCapacity := .Values.server.runtimeControl.webCapacity }}
{{- $webHardLimits := .Values.server.runtimeControl.webHardLimits }}
{{- $objectStorageEndpoint := include "azents.objectStorageEndpoint" . }}
{{- $objectStoragePublicEndpoint := include "azents.objectStoragePublicEndpoint" . }}
{{- $objectStorageBucket := include "azents.objectStorageBucket" . }}
{{- if not $objectStorageBucket }}
{{- fail "objectStorage.external.bucket is required when Runtime Control is enabled" }}
{{- end }}
{{- if not $objectStoragePublicEndpoint }}
{{- fail "objectStorage.external.publicEndpoint is required when Runtime Control is enabled" }}
{{- end }}
{{- if and (eq $transfer.stateBackend "memory") (or (ne (int .Values.server.runtimeControl.replicas) 1) .Values.server.runtimeControl.autoscaling.enabled) }}
{{- fail "memory Runtime Transfer state requires exactly one runtime-control replica and disabled autoscaling" }}
{{- end }}
{{- if and $webTransport.enabled (or (eq (int .Values.server.runtimeControl.metricsPort) 8030) (eq (int .Values.server.runtimeControl.metricsPort) (int $webTransport.trustedPort))) }}
{{- fail "server.runtimeControl.metricsPort must be separate from Runtime Control gRPC and trusted Web ports" }}
{{- end }}
{{- if and $webTransport.enabled (gt (int $webCapacity.maximumSseStreams) (int $webCapacity.maximumActiveStreams)) }}
{{- fail "server.runtimeControl.webCapacity.maximumSseStreams must not exceed maximumActiveStreams" }}
{{- end }}
{{- if and $webTransport.enabled (gt (int $webCapacity.maximumWebsocketStreams) (int $webCapacity.maximumActiveStreams)) }}
{{- fail "server.runtimeControl.webCapacity.maximumWebsocketStreams must not exceed maximumActiveStreams" }}
{{- end }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: runtime-control
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: {{ .Values.server.runtimeControl.replicas }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "runtime-control"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
    spec:
      {{- if $webTransport.enabled }}
      terminationGracePeriodSeconds: {{ .Values.server.runtimeControl.terminationGracePeriodSeconds }}
      {{- end }}
      serviceAccountName: {{ include "azents.serverServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: runtime-control
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["./bin/runtime-control.sh"]
          ports:
            - name: grpc
              containerPort: 8030
            {{- if $webTransport.enabled }}
            - name: trusted-web
              containerPort: {{ $webTransport.trustedPort }}
            - name: operations
              containerPort: {{ .Values.server.runtimeControl.metricsPort }}
            {{- end }}
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            - name: AZ_RUNTIME_CONTROL_PORT
              value: "8030"
            - name: AZ_RUNTIME_CONTROL_INSTANCE_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            {{- if $webTransport.enabled }}
            - name: AZ_RUNTIME_CONTROL_POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: AZ_RUNTIME_CONTROL_WEB_TRANSPORT_ENABLED
              value: "true"
            - name: AZ_RUNTIME_CONTROL_TRUSTED_PORT
              value: {{ printf "%d" (int64 $webTransport.trustedPort) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRUSTED_ADVERTISE_ADDRESS
              value: "$(AZ_RUNTIME_CONTROL_INSTANCE_ID).runtime-control-headless.$(AZ_RUNTIME_CONTROL_POD_NAMESPACE).svc:{{ $webTransport.trustedPort }}"
            - name: AZ_RUNTIME_CONTROL_TRUSTED_GATEWAY_PEER_IDENTITIES
              value: {{ required "server.runtimeControl.webTransport.gatewayPeerIdentities is required when trusted Runtime Web transport is enabled" $webTransport.gatewayPeerIdentities | quote }}
            - name: AZ_RUNTIME_CONTROL_TRUSTED_CONTROL_PEER_IDENTITIES
              value: {{ required "server.runtimeControl.webTransport.controlPeerIdentities is required when trusted Runtime Web transport is enabled" $webTransport.controlPeerIdentities | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_ROUTE_LEASE_SECONDS
              value: {{ printf "%v" $webTransport.routeLeaseSeconds | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_METRICS_PORT
              value: {{ printf "%d" (int64 .Values.server.runtimeControl.metricsPort) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_BACKEND
              value: {{ $webCapacity.backend | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_ACTIVE_STREAMS
              value: {{ printf "%d" (int64 $webCapacity.maximumActiveStreams) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_SSE_STREAMS
              value: {{ printf "%d" (int64 $webCapacity.maximumSseStreams) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_WEBSOCKET_STREAMS
              value: {{ printf "%d" (int64 $webCapacity.maximumWebsocketStreams) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_PENDING_OPENS
              value: {{ printf "%d" (int64 $webCapacity.maximumPendingOpens) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_BUFFER_BYTES
              value: {{ printf "%d" (int64 $webCapacity.maximumBufferBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_INBOUND_BYTES_PER_SECOND
              value: {{ printf "%d" (int64 $webCapacity.inboundBytesPerSecond) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_OUTBOUND_BYTES_PER_SECOND
              value: {{ printf "%d" (int64 $webCapacity.outboundBytesPerSecond) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_BURST_BYTES
              value: {{ printf "%d" (int64 $webCapacity.burstBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_NAMESPACE
              value: {{ $webCapacity.redisNamespace | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_TTL_SECONDS
              value: {{ printf "%d" (int64 $webCapacity.redisTtlSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_MAXIMUM_RELAY_SESSIONS
              value: {{ printf "%d" (int64 $webCapacity.maximumRelaySessions) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_SESSIONS
              value: {{ printf "%d" (int64 $webHardLimits.maximumSessions) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_ACTIVE_STREAMS
              value: {{ printf "%d" (int64 $webHardLimits.maximumActiveStreams) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_APPLICATION_BUFFER_BYTES
              value: {{ printf "%d" (int64 $webHardLimits.maximumApplicationBufferBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_CONTROL_BUFFER_BYTES
              value: {{ printf "%d" (int64 $webHardLimits.maximumControlBufferBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_QUEUED_ENVELOPES
              value: {{ printf "%d" (int64 $webHardLimits.maximumQueuedEnvelopes) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_PENDING_TASKS
              value: {{ printf "%d" (int64 $webHardLimits.maximumPendingTasks) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_EVENT_LOOP_LAG_MILLISECONDS
              value: {{ printf "%d" (int64 $webHardLimits.maximumEventLoopLagMilliseconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_RESIDENT_MEMORY_BYTES
              value: {{ printf "%d" (int64 $webHardLimits.maximumResidentMemoryBytes) | quote }}
            {{- end }}
            - name: AZ_RUNTIME_CONTROL_RECONCILE_INTERVAL_SECONDS
              value: {{ printf "%d" (int64 .Values.server.runtimeControl.reconcileIntervalSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_LIFECYCLE_RETRY_DELAY_SECONDS
              value: {{ printf "%d" (int64 .Values.server.runtimeControl.lifecycleRetryDelaySeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_START_TIMEOUT_SECONDS
              value: {{ printf "%d" (int64 .Values.server.runtimeControl.startTimeoutSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_BACKEND
              value: {{ $transfer.stateBackend | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_REDIS_NAMESPACE
              value: {{ $transfer.redisNamespace | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_PER_RUNTIME_ATTEMPTS
              value: {{ printf "%d" (int64 $transfer.perRuntimeAttempts) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_PER_RUNTIME_BYTES
              value: {{ printf "%d" (int64 $transfer.perRuntimeBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_DEPLOYMENT_ATTEMPTS
              value: {{ printf "%d" (int64 $transfer.deploymentAttempts) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_DEPLOYMENT_BYTES
              value: {{ printf "%d" (int64 $transfer.deploymentBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_ADMISSION_LEASE_SECONDS
              value: {{ printf "%d" (int64 $transfer.admissionLeaseSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_CONSUMER_LEASE_SECONDS
              value: {{ printf "%d" (int64 $transfer.consumerLeaseSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_STREAM_LEASE_SECONDS
              value: {{ printf "%d" (int64 $transfer.streamLeaseSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_TERMINAL_TTL_SECONDS
              value: {{ printf "%d" (int64 $transfer.terminalTtlSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_LIST_PAGE_SIZE
              value: {{ printf "%d" (int64 $transfer.listPageSize) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_MAX_CONCURRENT_DOWNLOADS
              value: {{ printf "%d" (int64 $transfer.maxConcurrentDownloads) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_MAX_CONCURRENT_UPLOADS
              value: {{ printf "%d" (int64 $transfer.maxConcurrentUploads) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_CHUNK_BYTES
              value: {{ printf "%d" (int64 $transfer.chunkBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_MULTIPART_PART_BYTES
              value: {{ printf "%d" (int64 $transfer.multipartPartBytes) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_REPAIR_INTERVAL_SECONDS
              value: {{ printf "%d" (int64 $transfer.repairIntervalSeconds) | quote }}
            - name: AZ_RUNTIME_CONTROL_TRANSFER_OBJECT_PREFIX
              value: {{ $transfer.objectPrefix | quote }}
            - name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_PREFIX
              value: {{ default "v1" (index .Values.server.env "AZ_WORKSPACE_S3_PREFIX") | quote }}
            {{- if $objectStorageEndpoint }}
            - name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_ENDPOINT_URL
              value: {{ $objectStorageEndpoint | quote }}
            {{- end }}
            {{- if $objectStoragePublicEndpoint }}
            - name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_PUBLIC_ENDPOINT_URL
              value: {{ $objectStoragePublicEndpoint | quote }}
            {{- end }}
            {{- if $objectStorageBucket }}
            - name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_BUCKET
              value: {{ $objectStorageBucket | quote }}
            {{- end }}
            - name: AZ_RUNTIME_CONTROL_ALLOW_INSECURE
              value: "false"
            - name: AZ_RUNTIME_CONTROL_KUBERNETES_TOKEN_REVIEW_ENABLED
              value: {{ .Values.runtimeProviderKubernetes.enabled | quote }}
            - name: AZ_RUNTIME_CONTROL_TLS_CERTIFICATE_FILE
              value: "/var/run/secrets/azents/runtime-control-tls/tls.crt"
            - name: AZ_RUNTIME_CONTROL_TLS_PRIVATE_KEY_FILE
              value: "/var/run/secrets/azents/runtime-control-tls/tls.key"
            - name: AZ_RUNTIME_CONTROL_TLS_CA_FILE
              value: "/var/run/secrets/azents/runtime-control-tls/ca.crt"
            - name: AZ_RUNTIME_RUNNER_IMAGE
              value: {{ include "azents.serverRuntimeRunnerImage" . | quote }}
            - name: AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT
              value: {{ include "azents.runtimeControlEndpoint" . | quote }}
            - name: AZ_RUNTIME_RUNNER_TRANSFER_ENDPOINT
              value: {{ include "azents.runtimeControlEndpoint" . | quote }}
            {{- include "azents.serverAuthSecretEnv" . | nindent 12 }}
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
            {{- include "azents.runtimeControlWorkspaceS3SecretEnv" . | nindent 12 }}
          volumeMounts:
            - name: runtime-control-tls
              mountPath: /var/run/secrets/azents/runtime-control-tls
              readOnly: true
          {{- if $webTransport.enabled }}
          readinessProbe:
            tcpSocket:
              port: grpc
            initialDelaySeconds: 5
            timeoutSeconds: 2
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /__azents/runtime-web/live
              port: operations
            initialDelaySeconds: 5
            timeoutSeconds: 2
            periodSeconds: 10
          startupProbe:
            httpGet:
              path: /__azents/runtime-web/live
              port: operations
            initialDelaySeconds: 5
            periodSeconds: 2
            failureThreshold: 30
          lifecycle:
            preStop:
              exec:
                command:
                  - python
                  - -c
                  - >-
                    import urllib.request;
                    urllib.request.urlopen(
                    urllib.request.Request(
                    "http://127.0.0.1:{{ .Values.server.runtimeControl.metricsPort }}/__azents/runtime-web/drain",
                    method="POST"), timeout=140).read()
          {{- else }}
          readinessProbe:
            tcpSocket:
              port: grpc
            initialDelaySeconds: 5
            timeoutSeconds: 2
            periodSeconds: 10
          startupProbe:
            tcpSocket:
              port: grpc
            initialDelaySeconds: 5
            periodSeconds: 2
            failureThreshold: 30
          {{- end }}
          {{- with .Values.server.runtimeControl.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
      volumes:
        - name: runtime-control-tls
          secret:
            secretName: {{ required "server.runtimeControl.tls.existingSecret is required when Runtime Control is enabled" .Values.server.runtimeControl.tls.existingSecret | quote }}
            items:
              - key: {{ .Values.server.runtimeControl.tls.certificateKey | quote }}
                path: tls.crt
              - key: {{ .Values.server.runtimeControl.tls.privateKeyKey | quote }}
                path: tls.key
              - key: {{ .Values.server.runtimeControl.tls.caKey | quote }}
                path: ca.crt
{{- end }}
