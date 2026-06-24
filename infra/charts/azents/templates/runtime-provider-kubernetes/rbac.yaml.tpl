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
{{- end }}
