# azentsadminclient.WorkspaceUserV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspaceuser_v1_create_workspace_user**](WorkspaceUserV1Api.md#workspaceuser_v1_create_workspace_user) | **POST** /workspace-user/v1/workspace-users | Create Workspace User
[**workspaceuser_v1_delete_workspace_user**](WorkspaceUserV1Api.md#workspaceuser_v1_delete_workspace_user) | **DELETE** /workspace-user/v1/workspace-users/{workspace_user_id} | Delete Workspace User
[**workspaceuser_v1_get_workspace_user**](WorkspaceUserV1Api.md#workspaceuser_v1_get_workspace_user) | **GET** /workspace-user/v1/workspace-users/{workspace_user_id} | Get Workspace User
[**workspaceuser_v1_list_workspace_users**](WorkspaceUserV1Api.md#workspaceuser_v1_list_workspace_users) | **GET** /workspace-user/v1/workspaces/{handle}/workspace-users | List Workspace Users
[**workspaceuser_v1_transfer_workspace_ownership**](WorkspaceUserV1Api.md#workspaceuser_v1_transfer_workspace_ownership) | **POST** /workspace-user/v1/workspaces/{handle}/transfer-ownership | Transfer Workspace Ownership
[**workspaceuser_v1_update_workspace_user**](WorkspaceUserV1Api.md#workspaceuser_v1_update_workspace_user) | **PATCH** /workspace-user/v1/workspace-users/{workspace_user_id} | Update Workspace User


# **workspaceuser_v1_create_workspace_user**
> WorkspaceUserResponse workspaceuser_v1_create_workspace_user(workspace_user_create_request)

Create Workspace User

Create a WorkspaceUser.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_user_create_request import WorkspaceUserCreateRequest
from azentsadminclient.models.workspace_user_response import WorkspaceUserResponse
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
    api_instance = azentsadminclient.WorkspaceUserV1Api(api_client)
    workspace_user_create_request = azentsadminclient.WorkspaceUserCreateRequest() # WorkspaceUserCreateRequest |

    try:
        # Create Workspace User
        api_response = api_instance.workspaceuser_v1_create_workspace_user(workspace_user_create_request)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_create_workspace_user:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_create_workspace_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_user_create_request** | [**WorkspaceUserCreateRequest**](WorkspaceUserCreateRequest.md)|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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

# **workspaceuser_v1_delete_workspace_user**
> workspaceuser_v1_delete_workspace_user(workspace_user_id)

Delete Workspace User

Delete a WorkspaceUser.

Owners cannot be deleted. Transfer ownership first, then delete.

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
    api_instance = azentsadminclient.WorkspaceUserV1Api(api_client)
    workspace_user_id = 'workspace_user_id_example' # str |

    try:
        # Delete Workspace User
        api_instance.workspaceuser_v1_delete_workspace_user(workspace_user_id)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_delete_workspace_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_user_id** | **str**|  |

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

# **workspaceuser_v1_get_workspace_user**
> WorkspaceUserResponse workspaceuser_v1_get_workspace_user(workspace_user_id)

Get Workspace User

Get a WorkspaceUser by ID.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_user_response import WorkspaceUserResponse
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
    api_instance = azentsadminclient.WorkspaceUserV1Api(api_client)
    workspace_user_id = 'workspace_user_id_example' # str |

    try:
        # Get Workspace User
        api_response = api_instance.workspaceuser_v1_get_workspace_user(workspace_user_id)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_get_workspace_user:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_get_workspace_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_user_id** | **str**|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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

# **workspaceuser_v1_list_workspace_users**
> WorkspaceUserListResponse workspaceuser_v1_list_workspace_users(handle)

List Workspace Users

List WorkspaceUsers in a Workspace.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_user_list_response import WorkspaceUserListResponse
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
    api_instance = azentsadminclient.WorkspaceUserV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Workspace Users
        api_response = api_instance.workspaceuser_v1_list_workspace_users(handle)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_list_workspace_users:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_list_workspace_users: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**WorkspaceUserListResponse**](WorkspaceUserListResponse.md)

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

# **workspaceuser_v1_transfer_workspace_ownership**
> WorkspaceUserResponse workspaceuser_v1_transfer_workspace_ownership(handle, transfer_ownership_request)

Transfer Workspace Ownership

Transfer Workspace ownership.

Set the new Owner and demote the previous Owner to Manager.

### Example


```python
import azentsadminclient
from azentsadminclient.models.transfer_ownership_request import TransferOwnershipRequest
from azentsadminclient.models.workspace_user_response import WorkspaceUserResponse
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
    api_instance = azentsadminclient.WorkspaceUserV1Api(api_client)
    handle = 'handle_example' # str |
    transfer_ownership_request = azentsadminclient.TransferOwnershipRequest() # TransferOwnershipRequest |

    try:
        # Transfer Workspace Ownership
        api_response = api_instance.workspaceuser_v1_transfer_workspace_ownership(handle, transfer_ownership_request)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_transfer_workspace_ownership:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_transfer_workspace_ownership: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **transfer_ownership_request** | [**TransferOwnershipRequest**](TransferOwnershipRequest.md)|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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

# **workspaceuser_v1_update_workspace_user**
> WorkspaceUserResponse workspaceuser_v1_update_workspace_user(workspace_user_id, workspace_user_update_request)

Update Workspace User

Update a WorkspaceUser.

### Example


```python
import azentsadminclient
from azentsadminclient.models.workspace_user_response import WorkspaceUserResponse
from azentsadminclient.models.workspace_user_update_request import WorkspaceUserUpdateRequest
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
    api_instance = azentsadminclient.WorkspaceUserV1Api(api_client)
    workspace_user_id = 'workspace_user_id_example' # str |
    workspace_user_update_request = azentsadminclient.WorkspaceUserUpdateRequest() # WorkspaceUserUpdateRequest |

    try:
        # Update Workspace User
        api_response = api_instance.workspaceuser_v1_update_workspace_user(workspace_user_id, workspace_user_update_request)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_update_workspace_user:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_update_workspace_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_user_id** | **str**|  |
 **workspace_user_update_request** | [**WorkspaceUserUpdateRequest**](WorkspaceUserUpdateRequest.md)|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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
