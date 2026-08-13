{{- if and .Values.runtimeProviderKubernetes.enabled .Values.global.rbac.create }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ printf "%s-runtime" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services", "configmaps"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "create", "update", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ printf "%s-runtime" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ printf "%s-runtime" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ printf "%s-leader" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "list", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ printf "%s-leader" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ printf "%s-leader" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ printf "%s-runtime-namespace-read" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: [""]
    resources: ["namespaces"]
    resourceNames:
      - {{ include "azents.runtimeProviderKubernetesWorkloadNamespace" . | quote }}
    verbs: ["get"]
  - apiGroups: ["authorization.k8s.io"]
    resources: ["selfsubjectaccessreviews"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {{ printf "%s-runtime-namespace-read" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {{ printf "%s-runtime-namespace-read" (include "azents.runtimeProviderKubernetesServiceAccountName" .) | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
{{ $mandatoryServices := list
  .Values.runtimeProviderKubernetes.strictNetwork.mandatoryServices.runtimeControl
  .Values.runtimeProviderKubernetes.strictNetwork.mandatoryServices.runtimeTransfer
-}}
{{- $seenMandatoryServices := dict -}}
{{- range $service := $mandatoryServices -}}
{{- $namespace := include "azents.runtimeProviderMandatoryServiceNamespace" (dict "root" $ "service" $service) -}}
{{- $key := printf "%s/%s" $namespace $service.name -}}
{{- if not (hasKey $seenMandatoryServices $key) -}}
{{- $_ := set $seenMandatoryServices $key true -}}
{{- $roleName := printf "%s-mandatory-service-%s" (include "azents.runtimeProviderKubernetesServiceAccountName" $) ($key | sha256sum | trunc 8) | trunc 63 | trimSuffix "-" -}}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ $roleName | quote }}
  namespace: {{ $namespace | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" $ "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
rules:
  - apiGroups: [""]
    resources: ["services"]
    resourceNames:
      - {{ $service.name | quote }}
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ $roleName | quote }}
  namespace: {{ $namespace | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" $ "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ $roleName | quote }}
subjects:
  - kind: ServiceAccount
    name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" $ | quote }}
    namespace: {{ include "azents.runtimeProviderKubernetesNamespace" $ | quote }}
{{- end -}}
{{- end }}
{{- end }}
