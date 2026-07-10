# azentsadminclient.WorkspaceV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspace_v1_bootstrap_first_owner**](WorkspaceV1Api.md#workspace_v1_bootstrap_first_owner) | **POST** /workspace/v1/bootstrap/first-owner | Bootstrap First Owner
[**workspace_v1_create_workspace**](WorkspaceV1Api.md#workspace_v1_create_workspace) | **POST** /workspace/v1/workspaces | Create Workspace
[**workspace_v1_delete_workspace**](WorkspaceV1Api.md#workspace_v1_delete_workspace) | **DELETE** /workspace/v1/workspaces/{handle} | Delete Workspace
[**workspace_v1_get_bootstrap_status**](WorkspaceV1Api.md#workspace_v1_get_bootstrap_status) | **GET** /workspace/v1/bootstrap/status | Get Bootstrap Status
[**workspace_v1_get_workspace**](WorkspaceV1Api.md#workspace_v1_get_workspace) | **GET** /workspace/v1/workspaces/{handle} | Get Workspace
[**workspace_v1_list_workspaces**](WorkspaceV1Api.md#workspace_v1_list_workspaces) | **GET** /workspace/v1/workspaces | List Workspaces
[**workspace_v1_update_workspace**](WorkspaceV1Api.md#workspace_v1_update_workspace) | **PATCH** /workspace/v1/workspaces/{handle} | Update Workspace


# **workspace_v1_bootstrap_first_owner**
> BootstrapFirstOwnerResponse workspace_v1_bootstrap_first_owner(bootstrap_first_owner_request)

Bootstrap First Owner

Create the first Owner and Workspace.

### Example


```python
import azentsadminclient
from azentsadminclient.models.bootstrap_first_owner_request import BootstrapFirstOwnerRequest
from azentsadminclient.models.bootstrap_first_owner_response import BootstrapFirstOwnerResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    bootstrap_first_owner_request = azentsadminclient.BootstrapFirstOwnerRequest() # BootstrapFirstOwnerRequest | 

    try:
        # Bootstrap First Owner
        api_response = api_instance.workspace_v1_bootstrap_first_owner(bootstrap_first_owner_request)
        print("The response of WorkspaceV1Api->workspace_v1_bootstrap_first_owner:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_bootstrap_first_owner: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **bootstrap_first_owner_request** | [**BootstrapFirstOwnerRequest**](BootstrapFirstOwnerRequest.md)|  | 

### Return type

[**BootstrapFirstOwnerResponse**](BootstrapFirstOwnerResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_create_workspace**
> WorkspaceResponse workspace_v1_create_workspace(workspace_create_request)

Create Workspace

Create a Workspace.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_create_request import WorkspaceCreateRequest
from azentsadminclient.models.workspace_response import WorkspaceResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    workspace_create_request = azentsadminclient.WorkspaceCreateRequest() # WorkspaceCreateRequest | 

    try:
        # Create Workspace
        api_response = api_instance.workspace_v1_create_workspace(workspace_create_request)
        print("The response of WorkspaceV1Api->workspace_v1_create_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_create_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_create_request** | [**WorkspaceCreateRequest**](WorkspaceCreateRequest.md)|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_delete_workspace**
> workspace_v1_delete_workspace(handle)

Delete Workspace

Delete a Workspace.

### Example


```python
import azentsadminclient
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Delete Workspace
        api_instance.workspace_v1_delete_workspace(handle)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_delete_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

void (empty response body)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_get_bootstrap_status**
> BootstrapStatusResponse workspace_v1_get_bootstrap_status()

Get Bootstrap Status

Get whether first owner bootstrap is available.

### Example


```python
import azentsadminclient
from azentsadminclient.models.bootstrap_status_response import BootstrapStatusResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)

    try:
        # Get Bootstrap Status
        api_response = api_instance.workspace_v1_get_bootstrap_status()
        print("The response of WorkspaceV1Api->workspace_v1_get_bootstrap_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_bootstrap_status: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**BootstrapStatusResponse**](BootstrapStatusResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_get_workspace**
> WorkspaceResponse workspace_v1_get_workspace(handle)

Get Workspace

Get a Workspace by handle.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_response import WorkspaceResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Workspace
        api_response = api_instance.workspace_v1_get_workspace(handle)
        print("The response of WorkspaceV1Api->workspace_v1_get_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_get_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_list_workspaces**
> WorkspaceListResponse workspace_v1_list_workspaces()

List Workspaces

List all Workspaces.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_list_response import WorkspaceListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)

    try:
        # List Workspaces
        api_response = api_instance.workspace_v1_list_workspaces()
        print("The response of WorkspaceV1Api->workspace_v1_list_workspaces:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_list_workspaces: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**WorkspaceListResponse**](WorkspaceListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_v1_update_workspace**
> WorkspaceResponse workspace_v1_update_workspace(handle, workspace_update_request)

Update Workspace

Update a Workspace.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_response import WorkspaceResponse
from azentsadminclient.models.workspace_update_request import WorkspaceUpdateRequest
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.WorkspaceV1Api(api_client)
    handle = 'handle_example' # str | 
    workspace_update_request = azentsadminclient.WorkspaceUpdateRequest() # WorkspaceUpdateRequest | 

    try:
        # Update Workspace
        api_response = api_instance.workspace_v1_update_workspace(handle, workspace_update_request)
        print("The response of WorkspaceV1Api->workspace_v1_update_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceV1Api->workspace_v1_update_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **workspace_update_request** | [**WorkspaceUpdateRequest**](WorkspaceUpdateRequest.md)|  | 

### Return type

[**WorkspaceResponse**](WorkspaceResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

