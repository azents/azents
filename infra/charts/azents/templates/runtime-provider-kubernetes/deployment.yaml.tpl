{{- if .Values.runtimeProviderKubernetes.enabled }}
{{- $runtimePodImagePullSecrets := .Values.global.imagePullSecrets -}}
{{- if ne .Values.runtimeProviderKubernetes.runtimePod.imagePullSecrets nil -}}
{{- $runtimePodImagePullSecrets = .Values.runtimeProviderKubernetes.runtimePod.imagePullSecrets -}}
{{- end -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: azents-runtime-provider-kubernetes
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: {{ .Values.runtimeProviderKubernetes.replicas }}
  selector:
    matchLabels:
      {{- include "azents.selectorLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
        {{- with .Values.global.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    spec:
      serviceAccountName: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.runtimeProviderKubernetes.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.runtimeProviderKubernetes.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: provider
          image: {{ include "azents.runtimeProviderKubernetesImage" . | quote }}
          imagePullPolicy: {{ .Values.runtimeProviderKubernetes.image.pullPolicy | quote }}
          env:
            - name: AZ_RUNTIME_CONTROL_ENDPOINT
              value: {{ include "azents.runtimeControlEndpoint" . | quote }}
            - name: AZ_RUNTIME_CONTROL_ALLOW_INSECURE
              value: "false"
            - name: AZ_RUNTIME_CONTROL_TLS_CA_FILE
              value: "/var/run/secrets/azents/runtime-control-tls/ca.crt"
            - name: AZ_RUNTIME_PROVIDER_READINESS_FILE
              value: "/tmp/azents-runtime-provider-ready"
            - name: AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE
              value: "/var/run/secrets/azents/runtime-provider-service-account-token/token"
            - name: AZ_RUNTIME_ENV
              value: {{ .Values.server.env.AZ_RUNTIME_ENV | quote }}
            - name: AZ_RUNTIME_PROVIDER_ID
              value: {{ .Values.runtimeProviderKubernetes.providerId | quote }}
            - name: AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE
              value: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
            - name: AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE
              value: {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
            - name: AZ_RUNTIME_PROVIDER_LEASE_NAME
              value: {{ .Values.runtimeProviderKubernetes.leaderElection.leaseName | quote }}
            - name: AZ_RUNTIME_PROVIDER_LEASE_DURATION_SECONDS
              value: {{ .Values.runtimeProviderKubernetes.leaderElection.leaseDurationSeconds | quote }}
            - name: AZ_RUNTIME_PROVIDER_WORKSPACE_PATH
              value: {{ .Values.runtimeProviderKubernetes.workspace.path | quote }}
            - name: AZ_RUNTIME_PROVIDER_STORAGE_CLASS
              value: {{ .Values.runtimeProviderKubernetes.storage.className | quote }}
            - name: AZ_RUNTIME_PROVIDER_PVC_SIZE
              value: {{ .Values.runtimeProviderKubernetes.storage.size | quote }}
            - name: AZ_RUNTIME_RUNNER_RESOURCES
              value: {{ .Values.runtimeProviderKubernetes.runnerResources | toJson | quote }}
            - name: AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION
              value: {{ .Values.runtimeProviderKubernetes.runnerLimits.maxConcurrentOperationsPerSession | quote }}
            - name: AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS
              value: {{ .Values.runtimeProviderKubernetes.runnerLimits.maxConcurrentSystemOperations | quote }}
            - name: AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS
              value: {{ .Values.runtimeProviderKubernetes.runnerLimits.maxConcurrentOperations | quote }}
            - name: AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER
              value: {{ .Values.runtimeProviderKubernetes.runnerLimits.maxPendingOperationsPerOwner | quote }}
            - name: AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS
              value: {{ .Values.runtimeProviderKubernetes.runnerLimits.maxPendingOperations | quote }}
            - name: AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS
              value: {{ .Values.runtimeProviderKubernetes.runnerLimits.maxConcurrentControlOperations | quote }}
            - name: AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS
              value: {{ $runtimePodImagePullSecrets | toJson | quote }}
            - name: AZ_RUNTIME_PROVIDER_POD_ANNOTATIONS
              value: {{ .Values.runtimeProviderKubernetes.runtimePod.annotations | toJson | quote }}
            - name: AZ_RUNTIME_PROVIDER_POD_NODE_SELECTOR
              value: {{ .Values.runtimeProviderKubernetes.runtimePod.nodeSelector | toJson | quote }}
            - name: AZ_RUNTIME_PROVIDER_POD_TOLERATIONS
              value: {{ .Values.runtimeProviderKubernetes.runtimePod.tolerations | toJson | quote }}
            - name: AZ_RUNTIME_RUNNER_IMAGE
              value: {{ include "azents.runtimeRunnerImage" . | quote }}
          volumeMounts:
            - name: runtime-control-tls
              mountPath: /var/run/secrets/azents/runtime-control-tls
              readOnly: true
            - name: runtime-provider-service-account-token
              mountPath: /var/run/secrets/azents/runtime-provider-service-account-token
              readOnly: true
          readinessProbe:
            exec:
              command:
                - python
                - -c
                - "from pathlib import Path; raise SystemExit(not Path('/tmp/azents-runtime-provider-ready').is_file())"
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 2
          {{- with .Values.runtimeProviderKubernetes.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
      volumes:
        - name: runtime-provider-service-account-token
          projected:
            sources:
              - serviceAccountToken:
                  audience: azents-runtime-control
                  path: token
        - name: runtime-control-tls
          secret:
            secretName: {{ required "server.runtimeControl.tls.existingSecret is required when the Kubernetes Provider is enabled" .Values.server.runtimeControl.tls.existingSecret | quote }}
            items:
              - key: {{ .Values.server.runtimeControl.tls.caKey | quote }}
                path: ca.crt
{{- end }}
