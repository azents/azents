# azentspublicclient.RuntimeExecutionV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_execution_v1_apply_agent_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_apply_agent_policy) | **POST** /runtime-execution/v1/workspaces/{handle}/agents/{agent_id}/apply | Apply Agent Policy
[**runtime_execution_v1_get_agent_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_get_agent_policy) | **GET** /runtime-execution/v1/workspaces/{handle}/agents/{agent_id}/settings | Get Agent Policy
[**runtime_execution_v1_get_workspace_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_get_workspace_policy) | **GET** /runtime-execution/v1/workspaces/{handle}/policy | Get Workspace Policy
[**runtime_execution_v1_list_agent_audit_events**](RuntimeExecutionV1Api.md#runtime_execution_v1_list_agent_audit_events) | **GET** /runtime-execution/v1/workspaces/{handle}/agents/{agent_id}/audit-events | List Agent Audit Events
[**runtime_execution_v1_list_workspace_audit_events**](RuntimeExecutionV1Api.md#runtime_execution_v1_list_workspace_audit_events) | **GET** /runtime-execution/v1/workspaces/{handle}/policy/audit-events | List Workspace Audit Events
[**runtime_execution_v1_list_workspace_profiles**](RuntimeExecutionV1Api.md#runtime_execution_v1_list_workspace_profiles) | **GET** /runtime-execution/v1/workspaces/{handle}/profiles | List Workspace Profiles
[**runtime_execution_v1_replace_agent_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_replace_agent_policy) | **PUT** /runtime-execution/v1/workspaces/{handle}/agents/{agent_id}/settings | Replace Agent Policy
[**runtime_execution_v1_replace_workspace_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_replace_workspace_policy) | **PUT** /runtime-execution/v1/workspaces/{handle}/policy | Replace Workspace Policy


# **runtime_execution_v1_apply_agent_policy**
> AgentRuntimeExecutionPolicyApplyResponse runtime_execution_v1_apply_agent_policy(agent_id, handle)

Apply Agent Policy

Apply current valid Agent execution intent to its Runtime.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_execution_policy_apply_response import AgentRuntimeExecutionPolicyApplyResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Apply Agent Policy
        api_response = api_instance.runtime_execution_v1_apply_agent_policy(agent_id, handle)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_apply_agent_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_apply_agent_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentRuntimeExecutionPolicyApplyResponse**](AgentRuntimeExecutionPolicyApplyResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_get_agent_policy**
> AgentRuntimeExecutionPolicyResponse runtime_execution_v1_get_agent_policy(agent_id, handle)

Get Agent Policy

Return configured Agent execution intent and effective preview.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_execution_policy_response import AgentRuntimeExecutionPolicyResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Agent Policy
        api_response = api_instance.runtime_execution_v1_get_agent_policy(agent_id, handle)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_get_agent_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_get_agent_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**AgentRuntimeExecutionPolicyResponse**](AgentRuntimeExecutionPolicyResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_get_workspace_policy**
> WorkspaceRuntimeExecutionPolicyResponse runtime_execution_v1_get_workspace_policy(handle)

Get Workspace Policy

Return the current safe Workspace execution policy.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_execution_policy_response import WorkspaceRuntimeExecutionPolicyResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Workspace Policy
        api_response = api_instance.runtime_execution_v1_get_workspace_policy(handle)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_get_workspace_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_get_workspace_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**WorkspaceRuntimeExecutionPolicyResponse**](WorkspaceRuntimeExecutionPolicyResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_list_agent_audit_events**
> RuntimeExecutionPolicyAuditListResponse runtime_execution_v1_list_agent_audit_events(agent_id, handle, offset=offset, limit=limit)

List Agent Audit Events

List metadata-only Agent execution-policy audit history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_execution_policy_audit_list_response import RuntimeExecutionPolicyAuditListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Agent Audit Events
        api_response = api_instance.runtime_execution_v1_list_agent_audit_events(agent_id, handle, offset=offset, limit=limit)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_list_agent_audit_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_list_agent_audit_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**RuntimeExecutionPolicyAuditListResponse**](RuntimeExecutionPolicyAuditListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_list_workspace_audit_events**
> RuntimeExecutionPolicyAuditListResponse runtime_execution_v1_list_workspace_audit_events(handle, offset=offset, limit=limit)

List Workspace Audit Events

List metadata-only Workspace execution-policy audit history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_execution_policy_audit_list_response import RuntimeExecutionPolicyAuditListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Workspace Audit Events
        api_response = api_instance.runtime_execution_v1_list_workspace_audit_events(handle, offset=offset, limit=limit)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_list_workspace_audit_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_list_workspace_audit_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**RuntimeExecutionPolicyAuditListResponse**](RuntimeExecutionPolicyAuditListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_list_workspace_profiles**
> WorkspaceRuntimeExecutionProfileListResponse runtime_execution_v1_list_workspace_profiles(handle, include_retired=include_retired, offset=offset, limit=limit)

List Workspace Profiles

List Platform Profiles with Workspace-level availability reasons.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_execution_profile_list_response import WorkspaceRuntimeExecutionProfileListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    handle = 'handle_example' # str | 
    include_retired = False # bool |  (optional) (default to False)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Workspace Profiles
        api_response = api_instance.runtime_execution_v1_list_workspace_profiles(handle, include_retired=include_retired, offset=offset, limit=limit)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_list_workspace_profiles:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_list_workspace_profiles: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **include_retired** | **bool**|  | [optional] [default to False]
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**WorkspaceRuntimeExecutionProfileListResponse**](WorkspaceRuntimeExecutionProfileListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_replace_agent_policy**
> AgentRuntimeExecutionPolicyResponse runtime_execution_v1_replace_agent_policy(agent_id, handle, agent_runtime_execution_policy_replace_request)

Replace Agent Policy

Replace configured Agent Profile selection and restrictive override.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_execution_policy_replace_request import AgentRuntimeExecutionPolicyReplaceRequest
from azentspublicclient.models.agent_runtime_execution_policy_response import AgentRuntimeExecutionPolicyResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    agent_runtime_execution_policy_replace_request = azentspublicclient.AgentRuntimeExecutionPolicyReplaceRequest() # AgentRuntimeExecutionPolicyReplaceRequest | 

    try:
        # Replace Agent Policy
        api_response = api_instance.runtime_execution_v1_replace_agent_policy(agent_id, handle, agent_runtime_execution_policy_replace_request)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_replace_agent_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_replace_agent_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **agent_runtime_execution_policy_replace_request** | [**AgentRuntimeExecutionPolicyReplaceRequest**](AgentRuntimeExecutionPolicyReplaceRequest.md)|  | 

### Return type

[**AgentRuntimeExecutionPolicyResponse**](AgentRuntimeExecutionPolicyResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_execution_v1_replace_workspace_policy**
> WorkspaceRuntimeExecutionPolicyResponse runtime_execution_v1_replace_workspace_policy(handle, workspace_runtime_execution_policy_replace_request)

Replace Workspace Policy

Replace Workspace restrictions and complete Profile allowance.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_execution_policy_replace_request import WorkspaceRuntimeExecutionPolicyReplaceRequest
from azentspublicclient.models.workspace_runtime_execution_policy_response import WorkspaceRuntimeExecutionPolicyResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeExecutionV1Api(api_client)
    handle = 'handle_example' # str | 
    workspace_runtime_execution_policy_replace_request = azentspublicclient.WorkspaceRuntimeExecutionPolicyReplaceRequest() # WorkspaceRuntimeExecutionPolicyReplaceRequest | 

    try:
        # Replace Workspace Policy
        api_response = api_instance.runtime_execution_v1_replace_workspace_policy(handle, workspace_runtime_execution_policy_replace_request)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_replace_workspace_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_replace_workspace_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **workspace_runtime_execution_policy_replace_request** | [**WorkspaceRuntimeExecutionPolicyReplaceRequest**](WorkspaceRuntimeExecutionPolicyReplaceRequest.md)|  | 

### Return type

[**WorkspaceRuntimeExecutionPolicyResponse**](WorkspaceRuntimeExecutionPolicyResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

