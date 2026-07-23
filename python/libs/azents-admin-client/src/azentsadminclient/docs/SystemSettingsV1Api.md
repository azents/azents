# azentsadminclient.SystemSettingsV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**system_settings_v1_cancel_platform_github_app_candidate**](SystemSettingsV1Api.md#system_settings_v1_cancel_platform_github_app_candidate) | **DELETE** /system-setting/v1/sections/platform-github-app/candidate | Cancel Platform Github App Candidate
[**system_settings_v1_check_platform_github_app_health**](SystemSettingsV1Api.md#system_settings_v1_check_platform_github_app_health) | **POST** /system-setting/v1/sections/platform-github-app/health-check | Check Platform Github App Health
[**system_settings_v1_confirm_platform_github_app_candidate**](SystemSettingsV1Api.md#system_settings_v1_confirm_platform_github_app_candidate) | **POST** /system-setting/v1/sections/platform-github-app/candidate/confirm | Confirm Platform Github App Candidate
[**system_settings_v1_get_external_channel_files_setting**](SystemSettingsV1Api.md#system_settings_v1_get_external_channel_files_setting) | **GET** /system-setting/v1/sections/external-channel-files | Get External Channel Files Setting
[**system_settings_v1_get_platform_github_app_setting**](SystemSettingsV1Api.md#system_settings_v1_get_platform_github_app_setting) | **GET** /system-setting/v1/sections/platform-github-app | Get Platform Github App Setting
[**system_settings_v1_list_system_setting_audit_events**](SystemSettingsV1Api.md#system_settings_v1_list_system_setting_audit_events) | **GET** /system-setting/v1/audit-events | List System Setting Audit Events
[**system_settings_v1_list_system_setting_sections**](SystemSettingsV1Api.md#system_settings_v1_list_system_setting_sections) | **GET** /system-setting/v1/sections | List System Setting Sections
[**system_settings_v1_patch_external_channel_files_setting**](SystemSettingsV1Api.md#system_settings_v1_patch_external_channel_files_setting) | **PATCH** /system-setting/v1/sections/external-channel-files | Patch External Channel Files Setting
[**system_settings_v1_patch_platform_github_app_setting**](SystemSettingsV1Api.md#system_settings_v1_patch_platform_github_app_setting) | **PATCH** /system-setting/v1/sections/platform-github-app | Patch Platform Github App Setting
[**system_settings_v1_validate_platform_github_app_candidate**](SystemSettingsV1Api.md#system_settings_v1_validate_platform_github_app_candidate) | **POST** /system-setting/v1/sections/platform-github-app/candidate/validate | Validate Platform Github App Candidate


# **system_settings_v1_cancel_platform_github_app_candidate**
> system_settings_v1_cancel_platform_github_app_candidate(candidate_id)

Cancel Platform Github App Candidate

Cancel the current candidate and delete its ciphertext.

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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)
    candidate_id = 'candidate_id_example' # str | 

    try:
        # Cancel Platform Github App Candidate
        api_instance.system_settings_v1_cancel_platform_github_app_candidate(candidate_id)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_cancel_platform_github_app_candidate: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **candidate_id** | **str**|  | 

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

# **system_settings_v1_check_platform_github_app_health**
> PlatformGitHubAppDetailResponse system_settings_v1_check_platform_github_app_health()

Check Platform Github App Health

Run an explicit health check for the current effective setting.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.platform_git_hub_app_detail_response import PlatformGitHubAppDetailResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)

    try:
        # Check Platform Github App Health
        api_response = api_instance.system_settings_v1_check_platform_github_app_health()
        print("The response of SystemSettingsV1Api->system_settings_v1_check_platform_github_app_health:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_check_platform_github_app_health: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**PlatformGitHubAppDetailResponse**](PlatformGitHubAppDetailResponse.md)

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

# **system_settings_v1_confirm_platform_github_app_candidate**
> PlatformGitHubAppDetailResponse system_settings_v1_confirm_platform_github_app_candidate(platform_git_hub_app_confirm_request)

Confirm Platform Github App Candidate

Confirm unchanged impact and activate a valid candidate.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.platform_git_hub_app_confirm_request import PlatformGitHubAppConfirmRequest
from azentsadminclient.models.platform_git_hub_app_detail_response import PlatformGitHubAppDetailResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)
    platform_git_hub_app_confirm_request = azentsadminclient.PlatformGitHubAppConfirmRequest() # PlatformGitHubAppConfirmRequest | 

    try:
        # Confirm Platform Github App Candidate
        api_response = api_instance.system_settings_v1_confirm_platform_github_app_candidate(platform_git_hub_app_confirm_request)
        print("The response of SystemSettingsV1Api->system_settings_v1_confirm_platform_github_app_candidate:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_confirm_platform_github_app_candidate: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **platform_git_hub_app_confirm_request** | [**PlatformGitHubAppConfirmRequest**](PlatformGitHubAppConfirmRequest.md)|  | 

### Return type

[**PlatformGitHubAppDetailResponse**](PlatformGitHubAppDetailResponse.md)

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

# **system_settings_v1_get_external_channel_files_setting**
> ExternalChannelFilesDetailResponse system_settings_v1_get_external_channel_files_setting()

Get External Channel Files Setting

Return the effective External Channel file policy.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.external_channel_files_detail_response import ExternalChannelFilesDetailResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)

    try:
        # Get External Channel Files Setting
        api_response = api_instance.system_settings_v1_get_external_channel_files_setting()
        print("The response of SystemSettingsV1Api->system_settings_v1_get_external_channel_files_setting:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_get_external_channel_files_setting: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**ExternalChannelFilesDetailResponse**](ExternalChannelFilesDetailResponse.md)

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

# **system_settings_v1_get_platform_github_app_setting**
> PlatformGitHubAppDetailResponse system_settings_v1_get_platform_github_app_setting()

Get Platform Github App Setting

Return the redacted Platform GitHub App detail.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.platform_git_hub_app_detail_response import PlatformGitHubAppDetailResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)

    try:
        # Get Platform Github App Setting
        api_response = api_instance.system_settings_v1_get_platform_github_app_setting()
        print("The response of SystemSettingsV1Api->system_settings_v1_get_platform_github_app_setting:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_get_platform_github_app_setting: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**PlatformGitHubAppDetailResponse**](PlatformGitHubAppDetailResponse.md)

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

# **system_settings_v1_list_system_setting_audit_events**
> SystemSettingAuditEventListResponse system_settings_v1_list_system_setting_audit_events(offset=offset, limit=limit)

List System Setting Audit Events

List metadata-only System Settings audit events.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_setting_audit_event_list_response import SystemSettingAuditEventListResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List System Setting Audit Events
        api_response = api_instance.system_settings_v1_list_system_setting_audit_events(offset=offset, limit=limit)
        print("The response of SystemSettingsV1Api->system_settings_v1_list_system_setting_audit_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_list_system_setting_audit_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**SystemSettingAuditEventListResponse**](SystemSettingAuditEventListResponse.md)

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

# **system_settings_v1_list_system_setting_sections**
> SystemSettingInventoryResponse system_settings_v1_list_system_setting_sections()

List System Setting Sections

List the redacted System Settings inventory.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_setting_inventory_response import SystemSettingInventoryResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)

    try:
        # List System Setting Sections
        api_response = api_instance.system_settings_v1_list_system_setting_sections()
        print("The response of SystemSettingsV1Api->system_settings_v1_list_system_setting_sections:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_list_system_setting_sections: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SystemSettingInventoryResponse**](SystemSettingInventoryResponse.md)

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

# **system_settings_v1_patch_external_channel_files_setting**
> ExternalChannelFilesDetailResponse system_settings_v1_patch_external_channel_files_setting(external_channel_files_patch_request)

Patch External Channel Files Setting

Directly activate an optimistic External Channel file policy patch.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.external_channel_files_detail_response import ExternalChannelFilesDetailResponse
from azentsadminclient.models.external_channel_files_patch_request import ExternalChannelFilesPatchRequest
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)
    external_channel_files_patch_request = azentsadminclient.ExternalChannelFilesPatchRequest() # ExternalChannelFilesPatchRequest | 

    try:
        # Patch External Channel Files Setting
        api_response = api_instance.system_settings_v1_patch_external_channel_files_setting(external_channel_files_patch_request)
        print("The response of SystemSettingsV1Api->system_settings_v1_patch_external_channel_files_setting:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_patch_external_channel_files_setting: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **external_channel_files_patch_request** | [**ExternalChannelFilesPatchRequest**](ExternalChannelFilesPatchRequest.md)|  | 

### Return type

[**ExternalChannelFilesDetailResponse**](ExternalChannelFilesDetailResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**409** | The expected System Settings version is stale. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **system_settings_v1_patch_platform_github_app_setting**
> PlatformGitHubAppDetailResponse system_settings_v1_patch_platform_github_app_setting(platform_git_hub_app_patch_request)

Patch Platform Github App Setting

Patch the Admin base and validate the resulting candidate.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.platform_git_hub_app_detail_response import PlatformGitHubAppDetailResponse
from azentsadminclient.models.platform_git_hub_app_patch_request import PlatformGitHubAppPatchRequest
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)
    platform_git_hub_app_patch_request = azentsadminclient.PlatformGitHubAppPatchRequest() # PlatformGitHubAppPatchRequest | 

    try:
        # Patch Platform Github App Setting
        api_response = api_instance.system_settings_v1_patch_platform_github_app_setting(platform_git_hub_app_patch_request)
        print("The response of SystemSettingsV1Api->system_settings_v1_patch_platform_github_app_setting:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_patch_platform_github_app_setting: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **platform_git_hub_app_patch_request** | [**PlatformGitHubAppPatchRequest**](PlatformGitHubAppPatchRequest.md)|  | 

### Return type

[**PlatformGitHubAppDetailResponse**](PlatformGitHubAppDetailResponse.md)

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

# **system_settings_v1_validate_platform_github_app_candidate**
> PlatformGitHubAppDetailResponse system_settings_v1_validate_platform_github_app_candidate()

Validate Platform Github App Candidate

Retry external validation for the current candidate.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.platform_git_hub_app_detail_response import PlatformGitHubAppDetailResponse
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
    api_instance = azentsadminclient.SystemSettingsV1Api(api_client)

    try:
        # Validate Platform Github App Candidate
        api_response = api_instance.system_settings_v1_validate_platform_github_app_candidate()
        print("The response of SystemSettingsV1Api->system_settings_v1_validate_platform_github_app_candidate:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemSettingsV1Api->system_settings_v1_validate_platform_github_app_candidate: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**PlatformGitHubAppDetailResponse**](PlatformGitHubAppDetailResponse.md)

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

