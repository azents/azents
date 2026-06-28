# azentspublicclient.WorkspaceUserV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspaceuser_v1_delete_workspace_user**](WorkspaceUserV1Api.md#workspaceuser_v1_delete_workspace_user) | **DELETE** /workspace-user/v1/workspaces/{handle}/workspace-users/{workspace_user_id} | Delete Workspace User
[**workspaceuser_v1_get_current_member**](WorkspaceUserV1Api.md#workspaceuser_v1_get_current_member) | **GET** /workspace-user/v1/workspaces/{handle}/me | Get Current Member
[**workspaceuser_v1_get_my_profile**](WorkspaceUserV1Api.md#workspaceuser_v1_get_my_profile) | **GET** /workspace-user/v1/workspaces/{handle}/me/profile | Get My Profile
[**workspaceuser_v1_list_workspace_users**](WorkspaceUserV1Api.md#workspaceuser_v1_list_workspace_users) | **GET** /workspace-user/v1/workspaces/{handle}/workspace-users | List Workspace Users
[**workspaceuser_v1_update_my_profile**](WorkspaceUserV1Api.md#workspaceuser_v1_update_my_profile) | **PATCH** /workspace-user/v1/workspaces/{handle}/me/profile | Update My Profile
[**workspaceuser_v1_update_workspace_user_role**](WorkspaceUserV1Api.md#workspaceuser_v1_update_workspace_user_role) | **PATCH** /workspace-user/v1/workspaces/{handle}/workspace-users/{workspace_user_id} | Update Workspace User Role


# **workspaceuser_v1_delete_workspace_user**
> workspaceuser_v1_delete_workspace_user(workspace_user_id, handle)

Delete Workspace User

Delete a workspace member.

Requires member management permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
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
    api_instance = azentspublicclient.WorkspaceUserV1Api(api_client)
    workspace_user_id = 'workspace_user_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Delete Workspace User
        api_instance.workspaceuser_v1_delete_workspace_user(workspace_user_id, handle)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_delete_workspace_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_user_id** | **str**|  |
 **handle** | **str**|  |

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspaceuser_v1_get_current_member**
> CurrentMemberResponse workspaceuser_v1_get_current_member(handle)

Get Current Member

Return the current user's workspace member information.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.current_member_response import CurrentMemberResponse
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
    api_instance = azentspublicclient.WorkspaceUserV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Get Current Member
        api_response = api_instance.workspaceuser_v1_get_current_member(handle)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_get_current_member:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_get_current_member: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**CurrentMemberResponse**](CurrentMemberResponse.md)

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

# **workspaceuser_v1_get_my_profile**
> WorkspaceUserResponse workspaceuser_v1_get_my_profile(handle)

Get My Profile

Return the current user's workspace profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_user_response import WorkspaceUserResponse
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
    api_instance = azentspublicclient.WorkspaceUserV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Get My Profile
        api_response = api_instance.workspaceuser_v1_get_my_profile(handle)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_get_my_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_get_my_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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

# **workspaceuser_v1_list_workspace_users**
> WorkspaceUserListResponse workspaceuser_v1_list_workspace_users(handle)

List Workspace Users

List workspace members.

Requires member read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_user_list_response import WorkspaceUserListResponse
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
    api_instance = azentspublicclient.WorkspaceUserV1Api(api_client)
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

# **workspaceuser_v1_update_my_profile**
> WorkspaceUserResponse workspaceuser_v1_update_my_profile(handle, update_my_profile_request)

Update My Profile

Update the current user's workspace profile.

Name, locale, and similar fields can be changed.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.update_my_profile_request import UpdateMyProfileRequest
from azentspublicclient.models.workspace_user_response import WorkspaceUserResponse
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
    api_instance = azentspublicclient.WorkspaceUserV1Api(api_client)
    handle = 'handle_example' # str |
    update_my_profile_request = azentspublicclient.UpdateMyProfileRequest() # UpdateMyProfileRequest |

    try:
        # Update My Profile
        api_response = api_instance.workspaceuser_v1_update_my_profile(handle, update_my_profile_request)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_update_my_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_update_my_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **update_my_profile_request** | [**UpdateMyProfileRequest**](UpdateMyProfileRequest.md)|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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

# **workspaceuser_v1_update_workspace_user_role**
> WorkspaceUserResponse workspaceuser_v1_update_workspace_user_role(workspace_user_id, handle, update_workspace_user_role_request)

Update Workspace User Role

Change a workspace member role.

Requires member management permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.update_workspace_user_role_request import UpdateWorkspaceUserRoleRequest
from azentspublicclient.models.workspace_user_response import WorkspaceUserResponse
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
    api_instance = azentspublicclient.WorkspaceUserV1Api(api_client)
    workspace_user_id = 'workspace_user_id_example' # str |
    handle = 'handle_example' # str |
    update_workspace_user_role_request = azentspublicclient.UpdateWorkspaceUserRoleRequest() # UpdateWorkspaceUserRoleRequest |

    try:
        # Update Workspace User Role
        api_response = api_instance.workspaceuser_v1_update_workspace_user_role(workspace_user_id, handle, update_workspace_user_role_request)
        print("The response of WorkspaceUserV1Api->workspaceuser_v1_update_workspace_user_role:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceUserV1Api->workspaceuser_v1_update_workspace_user_role: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **workspace_user_id** | **str**|  |
 **handle** | **str**|  |
 **update_workspace_user_role_request** | [**UpdateWorkspaceUserRoleRequest**](UpdateWorkspaceUserRoleRequest.md)|  |

### Return type

[**WorkspaceUserResponse**](WorkspaceUserResponse.md)

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

