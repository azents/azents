# azentsadminclient.SystemV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**system_v1_get_system_admin_me**](SystemV1Api.md#system_v1_get_system_admin_me) | **GET** /system/v1/me | Get System Admin Me
[**system_v1_grant_system_admin**](SystemV1Api.md#system_v1_grant_system_admin) | **PUT** /system/v1/users/{user_id}/roles/system_admin | Grant System Admin
[**system_v1_list_system_role_assignments**](SystemV1Api.md#system_v1_list_system_role_assignments) | **GET** /system/v1/role-assignments | List System Role Assignments
[**system_v1_revoke_system_admin**](SystemV1Api.md#system_v1_revoke_system_admin) | **DELETE** /system/v1/users/{user_id}/roles/system_admin | Revoke System Admin


# **system_v1_get_system_admin_me**
> SystemAdminMeResponse system_v1_get_system_admin_me()

Get System Admin Me

Return the current system administrator.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_admin_me_response import SystemAdminMeResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.SystemV1Api(api_client)

    try:
        # Get System Admin Me
        api_response = api_instance.system_v1_get_system_admin_me()
        print("The response of SystemV1Api->system_v1_get_system_admin_me:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_get_system_admin_me: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SystemAdminMeResponse**](SystemAdminMeResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **system_v1_grant_system_admin**
> SystemUserRoleAssignmentResponse system_v1_grant_system_admin(user_id)

Grant System Admin

Grant system administrator authority to an existing User.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_user_role_assignment_response import SystemUserRoleAssignmentResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.SystemV1Api(api_client)
    user_id = 'user_id_example' # str |

    try:
        # Grant System Admin
        api_response = api_instance.system_v1_grant_system_admin(user_id)
        print("The response of SystemV1Api->system_v1_grant_system_admin:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_grant_system_admin: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **user_id** | **str**|  |

### Return type

[**SystemUserRoleAssignmentResponse**](SystemUserRoleAssignmentResponse.md)

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

# **system_v1_list_system_role_assignments**
> SystemUserRoleAssignmentListResponse system_v1_list_system_role_assignments(offset=offset, limit=limit)

List System Role Assignments

List instance-wide role assignments.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_user_role_assignment_list_response import SystemUserRoleAssignmentListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.SystemV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List System Role Assignments
        api_response = api_instance.system_v1_list_system_role_assignments(offset=offset, limit=limit)
        print("The response of SystemV1Api->system_v1_list_system_role_assignments:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_list_system_role_assignments: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**SystemUserRoleAssignmentListResponse**](SystemUserRoleAssignmentListResponse.md)

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

# **system_v1_revoke_system_admin**
> system_v1_revoke_system_admin(user_id)

Revoke System Admin

Revoke system administrator authority from a User.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.SystemV1Api(api_client)
    user_id = 'user_id_example' # str |

    try:
        # Revoke System Admin
        api_instance.system_v1_revoke_system_admin(user_id)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_revoke_system_admin: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **user_id** | **str**|  |

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
