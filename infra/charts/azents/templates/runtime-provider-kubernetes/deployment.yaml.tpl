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
            {{- if .Values.server.runtimeControl.auth.enabled }}
            - name: AZ_RUNTIME_CONTROL_AUTH_TOKEN
              valueFrom:
                secretKeyRef:
                  name: {{ required "server.runtimeControl.auth.existingSecret is required when Runtime Control auth is enabled" .Values.server.runtimeControl.auth.existingSecret | quote }}
                  key: {{ required "server.runtimeControl.auth.tokenKey is required when Runtime Control auth is enabled" .Values.server.runtimeControl.auth.tokenKey | quote }}
            {{- end }}
            - name: AZ_RUNTIME_PROVIDER_AUTH_CREDENTIAL_ID
              value: {{ .Values.runtimeProviderKubernetes.providerId | quote }}
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
          {{- with .Values.runtimeProviderKubernetes.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
{{- end }}
