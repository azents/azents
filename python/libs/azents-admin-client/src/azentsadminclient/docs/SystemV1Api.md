# azentsadminclient.SystemV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**system_v1_get_archive_retention_application**](SystemV1Api.md#system_v1_get_archive_retention_application) | **GET** /system/v1/settings/file-lifecycle/retention-applications/{application_id} | Get Archive Retention Application
[**system_v1_get_file_lifecycle_settings**](SystemV1Api.md#system_v1_get_file_lifecycle_settings) | **GET** /system/v1/settings/file-lifecycle | Get File Lifecycle Settings
[**system_v1_get_system_admin_me**](SystemV1Api.md#system_v1_get_system_admin_me) | **GET** /system/v1/me | Get System Admin Me
[**system_v1_grant_system_admin**](SystemV1Api.md#system_v1_grant_system_admin) | **PUT** /system/v1/users/{user_id}/roles/system_admin | Grant System Admin
[**system_v1_list_system_role_assignments**](SystemV1Api.md#system_v1_list_system_role_assignments) | **GET** /system/v1/role-assignments | List System Role Assignments
[**system_v1_preview_archive_retention_update**](SystemV1Api.md#system_v1_preview_archive_retention_update) | **POST** /system/v1/settings/file-lifecycle/archive-retention/preview | Preview Archive Retention Update
[**system_v1_revoke_system_admin**](SystemV1Api.md#system_v1_revoke_system_admin) | **DELETE** /system/v1/users/{user_id}/roles/system_admin | Revoke System Admin
[**system_v1_update_file_lifecycle_settings**](SystemV1Api.md#system_v1_update_file_lifecycle_settings) | **PATCH** /system/v1/settings/file-lifecycle | Update File Lifecycle Settings


# **system_v1_get_archive_retention_application**
> ArchiveRetentionApplicationResponse system_v1_get_archive_retention_application(application_id)

Get Archive Retention Application

Return durable existing-archive recalculation progress.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.archive_retention_application_response import ArchiveRetentionApplicationResponse
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
    application_id = 'application_id_example' # str | 

    try:
        # Get Archive Retention Application
        api_response = api_instance.system_v1_get_archive_retention_application(application_id)
        print("The response of SystemV1Api->system_v1_get_archive_retention_application:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_get_archive_retention_application: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **application_id** | **str**|  | 

### Return type

[**ArchiveRetentionApplicationResponse**](ArchiveRetentionApplicationResponse.md)

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

# **system_v1_get_file_lifecycle_settings**
> FileLifecycleSettingsResponse system_v1_get_file_lifecycle_settings()

Get File Lifecycle Settings

Return instance-wide archive retention settings.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.file_lifecycle_settings_response import FileLifecycleSettingsResponse
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
        # Get File Lifecycle Settings
        api_response = api_instance.system_v1_get_file_lifecycle_settings()
        print("The response of SystemV1Api->system_v1_get_file_lifecycle_settings:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_get_file_lifecycle_settings: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**FileLifecycleSettingsResponse**](FileLifecycleSettingsResponse.md)

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

# **system_v1_preview_archive_retention_update**
> ArchiveRetentionPreviewResponse system_v1_preview_archive_retention_update(archive_retention_preview_request)

Preview Archive Retention Update

Preview applying one retention value to existing archives.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.archive_retention_preview_request import ArchiveRetentionPreviewRequest
from azentsadminclient.models.archive_retention_preview_response import ArchiveRetentionPreviewResponse
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
    archive_retention_preview_request = azentsadminclient.ArchiveRetentionPreviewRequest() # ArchiveRetentionPreviewRequest | 

    try:
        # Preview Archive Retention Update
        api_response = api_instance.system_v1_preview_archive_retention_update(archive_retention_preview_request)
        print("The response of SystemV1Api->system_v1_preview_archive_retention_update:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_preview_archive_retention_update: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **archive_retention_preview_request** | [**ArchiveRetentionPreviewRequest**](ArchiveRetentionPreviewRequest.md)|  | 

### Return type

[**ArchiveRetentionPreviewResponse**](ArchiveRetentionPreviewResponse.md)

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

# **system_v1_update_file_lifecycle_settings**
> FileLifecycleSettingsUpdateResponse system_v1_update_file_lifecycle_settings(file_lifecycle_settings_update_request)

Update File Lifecycle Settings

Update archive retention settings with optimistic concurrency.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.file_lifecycle_settings_update_request import FileLifecycleSettingsUpdateRequest
from azentsadminclient.models.file_lifecycle_settings_update_response import FileLifecycleSettingsUpdateResponse
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
    file_lifecycle_settings_update_request = azentsadminclient.FileLifecycleSettingsUpdateRequest() # FileLifecycleSettingsUpdateRequest | 

    try:
        # Update File Lifecycle Settings
        api_response = api_instance.system_v1_update_file_lifecycle_settings(file_lifecycle_settings_update_request)
        print("The response of SystemV1Api->system_v1_update_file_lifecycle_settings:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemV1Api->system_v1_update_file_lifecycle_settings: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **file_lifecycle_settings_update_request** | [**FileLifecycleSettingsUpdateRequest**](FileLifecycleSettingsUpdateRequest.md)|  | 

### Return type

[**FileLifecycleSettingsUpdateResponse**](FileLifecycleSettingsUpdateResponse.md)

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

