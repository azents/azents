{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled }}
{{- $transfer := .Values.server.runtimeControl.transfer }}
{{- $objectStorageEndpoint := include "azents.objectStorageEndpoint" . }}
{{- $objectStorageBucket := include "azents.objectStorageBucket" . }}
{{- if and (eq $transfer.stateBackend "memory") (or (ne (int .Values.server.runtimeControl.replicas) 1) .Values.server.runtimeControl.autoscaling.enabled) }}
{{- fail "memory Runtime Transfer state requires exactly one runtime-control replica and disabled autoscaling" }}
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
