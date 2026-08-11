# azentspublicclient.RuntimeProfileV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_profile_v1_create_profile_recreation**](RuntimeProfileV1Api.md#runtime_profile_v1_create_profile_recreation) | **POST** /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id}/recreation-operations | Create Profile Recreation
[**runtime_profile_v1_create_workspace_runtime_profile**](RuntimeProfileV1Api.md#runtime_profile_v1_create_workspace_runtime_profile) | **POST** /runtime-profile/v1/workspaces/{handle}/profiles | Create Workspace Runtime Profile
[**runtime_profile_v1_delete_workspace_runtime_profile**](RuntimeProfileV1Api.md#runtime_profile_v1_delete_workspace_runtime_profile) | **DELETE** /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id} | Delete Workspace Runtime Profile
[**runtime_profile_v1_get_workspace_runtime_profile**](RuntimeProfileV1Api.md#runtime_profile_v1_get_workspace_runtime_profile) | **GET** /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id} | Get Workspace Runtime Profile
[**runtime_profile_v1_get_workspace_runtime_profile_default**](RuntimeProfileV1Api.md#runtime_profile_v1_get_workspace_runtime_profile_default) | **GET** /runtime-profile/v1/workspaces/{handle}/default | Get Workspace Runtime Profile Default
[**runtime_profile_v1_get_workspace_runtime_profile_recreation**](RuntimeProfileV1Api.md#runtime_profile_v1_get_workspace_runtime_profile_recreation) | **GET** /runtime-profile/v1/workspaces/{handle}/recreation-operations/{operation_id} | Get Workspace Runtime Profile Recreation
[**runtime_profile_v1_list_selectable_infrastructure_profiles**](RuntimeProfileV1Api.md#runtime_profile_v1_list_selectable_infrastructure_profiles) | **GET** /runtime-profile/v1/workspaces/{handle}/infrastructure-profiles | List Selectable Infrastructure Profiles
[**runtime_profile_v1_list_workspace_runtime_profiles**](RuntimeProfileV1Api.md#runtime_profile_v1_list_workspace_runtime_profiles) | **GET** /runtime-profile/v1/workspaces/{handle}/profiles | List Workspace Runtime Profiles
[**runtime_profile_v1_replace_workspace_runtime_profile**](RuntimeProfileV1Api.md#runtime_profile_v1_replace_workspace_runtime_profile) | **PUT** /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id} | Replace Workspace Runtime Profile
[**runtime_profile_v1_replace_workspace_runtime_profile_default**](RuntimeProfileV1Api.md#runtime_profile_v1_replace_workspace_runtime_profile_default) | **PUT** /runtime-profile/v1/workspaces/{handle}/default | Replace Workspace Runtime Profile Default


# **runtime_profile_v1_create_profile_recreation**
> RuntimeRecreationOperationResponse runtime_profile_v1_create_profile_recreation(profile_id, handle, runtime_recreation_create_request)

Create Profile Recreation

Start bounded recreation for one Workspace Runtime Profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_recreation_create_request import RuntimeRecreationCreateRequest
from azentspublicclient.models.runtime_recreation_operation_response import RuntimeRecreationOperationResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    profile_id = 'profile_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_recreation_create_request = azentspublicclient.RuntimeRecreationCreateRequest() # RuntimeRecreationCreateRequest | 

    try:
        # Create Profile Recreation
        api_response = api_instance.runtime_profile_v1_create_profile_recreation(profile_id, handle, runtime_recreation_create_request)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_create_profile_recreation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_create_profile_recreation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 
 **handle** | **str**|  | 
 **runtime_recreation_create_request** | [**RuntimeRecreationCreateRequest**](RuntimeRecreationCreateRequest.md)|  | 

### Return type

[**RuntimeRecreationOperationResponse**](RuntimeRecreationOperationResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_profile_v1_create_workspace_runtime_profile**
> WorkspaceRuntimeProfileResponse runtime_profile_v1_create_workspace_runtime_profile(handle, workspace_runtime_profile_create_request)

Create Workspace Runtime Profile

Create one complete Workspace Runtime choice.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_create_request import WorkspaceRuntimeProfileCreateRequest
from azentspublicclient.models.workspace_runtime_profile_response import WorkspaceRuntimeProfileResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    handle = 'handle_example' # str | 
    workspace_runtime_profile_create_request = azentspublicclient.WorkspaceRuntimeProfileCreateRequest() # WorkspaceRuntimeProfileCreateRequest | 

    try:
        # Create Workspace Runtime Profile
        api_response = api_instance.runtime_profile_v1_create_workspace_runtime_profile(handle, workspace_runtime_profile_create_request)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_create_workspace_runtime_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_create_workspace_runtime_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **workspace_runtime_profile_create_request** | [**WorkspaceRuntimeProfileCreateRequest**](WorkspaceRuntimeProfileCreateRequest.md)|  | 

### Return type

[**WorkspaceRuntimeProfileResponse**](WorkspaceRuntimeProfileResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_profile_v1_delete_workspace_runtime_profile**
> WorkspaceRuntimeProfileDeleteResponse runtime_profile_v1_delete_workspace_runtime_profile(profile_id, handle, workspace_runtime_profile_delete_request)

Delete Workspace Runtime Profile

Permanently delete one exact Workspace-owned Runtime Profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_delete_request import WorkspaceRuntimeProfileDeleteRequest
from azentspublicclient.models.workspace_runtime_profile_delete_response import WorkspaceRuntimeProfileDeleteResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    profile_id = 'profile_id_example' # str | 
    handle = 'handle_example' # str | 
    workspace_runtime_profile_delete_request = azentspublicclient.WorkspaceRuntimeProfileDeleteRequest() # WorkspaceRuntimeProfileDeleteRequest | 

    try:
        # Delete Workspace Runtime Profile
        api_response = api_instance.runtime_profile_v1_delete_workspace_runtime_profile(profile_id, handle, workspace_runtime_profile_delete_request)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_delete_workspace_runtime_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_delete_workspace_runtime_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 
 **handle** | **str**|  | 
 **workspace_runtime_profile_delete_request** | [**WorkspaceRuntimeProfileDeleteRequest**](WorkspaceRuntimeProfileDeleteRequest.md)|  | 

### Return type

[**WorkspaceRuntimeProfileDeleteResponse**](WorkspaceRuntimeProfileDeleteResponse.md)

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

# **runtime_profile_v1_get_workspace_runtime_profile**
> WorkspaceRuntimeProfileResponse runtime_profile_v1_get_workspace_runtime_profile(profile_id, handle)

Get Workspace Runtime Profile

Inspect one exact Workspace-owned Runtime Profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_response import WorkspaceRuntimeProfileResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    profile_id = 'profile_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Workspace Runtime Profile
        api_response = api_instance.runtime_profile_v1_get_workspace_runtime_profile(profile_id, handle)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_get_workspace_runtime_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_get_workspace_runtime_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**WorkspaceRuntimeProfileResponse**](WorkspaceRuntimeProfileResponse.md)

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

# **runtime_profile_v1_get_workspace_runtime_profile_default**
> WorkspaceRuntimeProfileDefaultResponse runtime_profile_v1_get_workspace_runtime_profile_default(handle)

Get Workspace Runtime Profile Default

Get the Workspace Runtime Profile default and its current availability.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_default_response import WorkspaceRuntimeProfileDefaultResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Workspace Runtime Profile Default
        api_response = api_instance.runtime_profile_v1_get_workspace_runtime_profile_default(handle)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_get_workspace_runtime_profile_default:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_get_workspace_runtime_profile_default: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**WorkspaceRuntimeProfileDefaultResponse**](WorkspaceRuntimeProfileDefaultResponse.md)

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

# **runtime_profile_v1_get_workspace_runtime_profile_recreation**
> RuntimeRecreationOperationResponse runtime_profile_v1_get_workspace_runtime_profile_recreation(operation_id, handle, offset=offset, limit=limit)

Get Workspace Runtime Profile Recreation

Read Workspace-scoped recreation progress and bounded failures.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_recreation_operation_response import RuntimeRecreationOperationResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    operation_id = 'operation_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # Get Workspace Runtime Profile Recreation
        api_response = api_instance.runtime_profile_v1_get_workspace_runtime_profile_recreation(operation_id, handle, offset=offset, limit=limit)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_get_workspace_runtime_profile_recreation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_get_workspace_runtime_profile_recreation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **operation_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**RuntimeRecreationOperationResponse**](RuntimeRecreationOperationResponse.md)

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

# **runtime_profile_v1_list_selectable_infrastructure_profiles**
> SelectableInfrastructureProfileListResponse runtime_profile_v1_list_selectable_infrastructure_profiles(handle)

List Selectable Infrastructure Profiles

List exact Provider infrastructure Profiles selectable by the Workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.selectable_infrastructure_profile_list_response import SelectableInfrastructureProfileListResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # List Selectable Infrastructure Profiles
        api_response = api_instance.runtime_profile_v1_list_selectable_infrastructure_profiles(handle)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_list_selectable_infrastructure_profiles:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_list_selectable_infrastructure_profiles: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**SelectableInfrastructureProfileListResponse**](SelectableInfrastructureProfileListResponse.md)

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

# **runtime_profile_v1_list_workspace_runtime_profiles**
> WorkspaceRuntimeProfileListResponse runtime_profile_v1_list_workspace_runtime_profiles(handle, include_disabled=include_disabled)

List Workspace Runtime Profiles

List Workspace-owned Runtime Profiles with current availability.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_list_response import WorkspaceRuntimeProfileListResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    handle = 'handle_example' # str | 
    include_disabled = False # bool |  (optional) (default to False)

    try:
        # List Workspace Runtime Profiles
        api_response = api_instance.runtime_profile_v1_list_workspace_runtime_profiles(handle, include_disabled=include_disabled)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_list_workspace_runtime_profiles:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_list_workspace_runtime_profiles: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **include_disabled** | **bool**|  | [optional] [default to False]

### Return type

[**WorkspaceRuntimeProfileListResponse**](WorkspaceRuntimeProfileListResponse.md)

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

# **runtime_profile_v1_replace_workspace_runtime_profile**
> WorkspaceRuntimeProfileResponse runtime_profile_v1_replace_workspace_runtime_profile(profile_id, handle, workspace_runtime_profile_replace_request)

Replace Workspace Runtime Profile

Replace one Workspace Profile with optimistic version fencing.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_replace_request import WorkspaceRuntimeProfileReplaceRequest
from azentspublicclient.models.workspace_runtime_profile_response import WorkspaceRuntimeProfileResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    profile_id = 'profile_id_example' # str | 
    handle = 'handle_example' # str | 
    workspace_runtime_profile_replace_request = azentspublicclient.WorkspaceRuntimeProfileReplaceRequest() # WorkspaceRuntimeProfileReplaceRequest | 

    try:
        # Replace Workspace Runtime Profile
        api_response = api_instance.runtime_profile_v1_replace_workspace_runtime_profile(profile_id, handle, workspace_runtime_profile_replace_request)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_replace_workspace_runtime_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_replace_workspace_runtime_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 
 **handle** | **str**|  | 
 **workspace_runtime_profile_replace_request** | [**WorkspaceRuntimeProfileReplaceRequest**](WorkspaceRuntimeProfileReplaceRequest.md)|  | 

### Return type

[**WorkspaceRuntimeProfileResponse**](WorkspaceRuntimeProfileResponse.md)

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

# **runtime_profile_v1_replace_workspace_runtime_profile_default**
> WorkspaceRuntimeProfileDefaultResponse runtime_profile_v1_replace_workspace_runtime_profile_default(handle, workspace_runtime_profile_default_replace_request)

Replace Workspace Runtime Profile Default

Set or clear the Workspace default with optimistic version fencing.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_runtime_profile_default_replace_request import WorkspaceRuntimeProfileDefaultReplaceRequest
from azentspublicclient.models.workspace_runtime_profile_default_response import WorkspaceRuntimeProfileDefaultResponse
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
    api_instance = azentspublicclient.RuntimeProfileV1Api(api_client)
    handle = 'handle_example' # str | 
    workspace_runtime_profile_default_replace_request = azentspublicclient.WorkspaceRuntimeProfileDefaultReplaceRequest() # WorkspaceRuntimeProfileDefaultReplaceRequest | 

    try:
        # Replace Workspace Runtime Profile Default
        api_response = api_instance.runtime_profile_v1_replace_workspace_runtime_profile_default(handle, workspace_runtime_profile_default_replace_request)
        print("The response of RuntimeProfileV1Api->runtime_profile_v1_replace_workspace_runtime_profile_default:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProfileV1Api->runtime_profile_v1_replace_workspace_runtime_profile_default: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **workspace_runtime_profile_default_replace_request** | [**WorkspaceRuntimeProfileDefaultReplaceRequest**](WorkspaceRuntimeProfileDefaultReplaceRequest.md)|  | 

### Return type

[**WorkspaceRuntimeProfileDefaultResponse**](WorkspaceRuntimeProfileDefaultResponse.md)

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

