# azentspublicclient.PersonalGitHubToolkitV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**personal_github_toolkit_v1_personal_github_access**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_access) | **GET** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/access | Personal Github Access
[**personal_github_toolkit_v1_personal_github_availability**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_availability) | **GET** /toolkit/v1/workspaces/{handle}/personal/github/setup-availability | Personal Github Availability
[**personal_github_toolkit_v1_personal_github_cancel**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/attempt | Personal Github Cancel
[**personal_github_toolkit_v1_personal_github_confirm**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_confirm) | **POST** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/confirm | Personal Github Confirm
[**personal_github_toolkit_v1_personal_github_connect**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_connect) | **POST** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/connect | Personal Github Connect
[**personal_github_toolkit_v1_personal_github_creation_app**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_creation_app) | **GET** /toolkit/v1/workspaces/{handle}/personal/github-user-creations/{attempt_id}/app | Personal Github Creation App
[**personal_github_toolkit_v1_personal_github_creation_cancel**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_creation_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/personal/github-user-creations/{attempt_id} | Personal Github Creation Cancel
[**personal_github_toolkit_v1_personal_github_creation_confirm**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_creation_confirm) | **POST** /toolkit/v1/workspaces/{handle}/personal/github-user-creations/confirm | Personal Github Creation Confirm
[**personal_github_toolkit_v1_personal_github_creation_connect**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_creation_connect) | **POST** /toolkit/v1/workspaces/{handle}/personal/github-user-creations/connect | Personal Github Creation Connect
[**personal_github_toolkit_v1_personal_github_creation_exchange**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_creation_exchange) | **POST** /toolkit/v1/workspaces/{handle}/personal/github-user-creations/exchange | Personal Github Creation Exchange
[**personal_github_toolkit_v1_personal_github_creation_review**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_creation_review) | **GET** /toolkit/v1/workspaces/{handle}/personal/github-user-creations/{attempt_id} | Personal Github Creation Review
[**personal_github_toolkit_v1_personal_github_disconnect**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_disconnect) | **DELETE** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/connection | Personal Github Disconnect
[**personal_github_toolkit_v1_personal_github_exchange**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_exchange) | **POST** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/exchange | Personal Github Exchange
[**personal_github_toolkit_v1_personal_github_install_url**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_install_url) | **GET** /toolkit/v1/workspaces/{handle}/personal/github/platform-install-url | Personal Github Install Url
[**personal_github_toolkit_v1_personal_github_installation_oauth_url**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_installation_oauth_url) | **GET** /toolkit/v1/workspaces/{handle}/personal/github/platform-oauth-url | Personal Github Installation Oauth Url
[**personal_github_toolkit_v1_personal_github_review**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_review) | **GET** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/review | Personal Github Review
[**personal_github_toolkit_v1_personal_github_setup_app**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_setup_app) | **GET** /toolkit/v1/workspaces/{handle}/personal/github/setup-app | Personal Github Setup App
[**personal_github_toolkit_v1_personal_github_setup_verify**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_setup_verify) | **POST** /toolkit/v1/workspaces/{handle}/personal/github/setup-verification | Personal Github Setup Verify
[**personal_github_toolkit_v1_personal_github_status**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_status) | **GET** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/github-user/connection | Personal Github Status
[**personal_github_toolkit_v1_personal_github_sync_installations**](PersonalGitHubToolkitV1Api.md#personal_github_toolkit_v1_personal_github_sync_installations) | **POST** /toolkit/v1/workspaces/{handle}/personal/github/platform-installations | Personal Github Sync Installations


# **personal_github_toolkit_v1_personal_github_access**
> GitHubUserAccessPage personal_github_toolkit_v1_personal_github_access(toolkit_id, handle, cursor=cursor)

Personal Github Access

Observe the exact owner's bounded account/App access through common checks.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_access_page import GitHubUserAccessPage
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    cursor = 'cursor_example' # str |  (optional)

    try:
        # Personal Github Access
        api_response = api_instance.personal_github_toolkit_v1_personal_github_access(toolkit_id, handle, cursor=cursor)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **cursor** | **str**|  | [optional] 

### Return type

[**GitHubUserAccessPage**](GitHubUserAccessPage.md)

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

# **personal_github_toolkit_v1_personal_github_availability**
> GitHubSetupAvailability personal_github_toolkit_v1_personal_github_availability(handle)

Personal Github Availability

Use the common auth-mode readiness without requiring a Workspace membership.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_setup_availability import GitHubSetupAvailability
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Personal Github Availability
        api_response = api_instance.personal_github_toolkit_v1_personal_github_availability(handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_availability:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_availability: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GitHubSetupAvailability**](GitHubSetupAvailability.md)

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

# **personal_github_toolkit_v1_personal_github_cancel**
> personal_github_toolkit_v1_personal_github_cancel(toolkit_id, handle, git_hub_user_attempt_request)

Personal Github Cancel

Cancel the exact owner's unpublished setup and clean up its candidate.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_attempt_request import GitHubUserAttemptRequest
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Personal Github Cancel
        api_instance.personal_github_toolkit_v1_personal_github_cancel(toolkit_id, handle, git_hub_user_attempt_request)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **git_hub_user_attempt_request** | [**GitHubUserAttemptRequest**](GitHubUserAttemptRequest.md)|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_github_toolkit_v1_personal_github_confirm**
> GitHubUserConnectionSummary personal_github_toolkit_v1_personal_github_confirm(toolkit_id, handle, git_hub_user_attempt_request)

Personal Github Confirm

Activate the reviewed personal grant using existing replacement checks.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_attempt_request import GitHubUserAttemptRequest
from azentspublicclient.models.git_hub_user_connection_summary import GitHubUserConnectionSummary
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Personal Github Confirm
        api_response = api_instance.personal_github_toolkit_v1_personal_github_confirm(toolkit_id, handle, git_hub_user_attempt_request)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **git_hub_user_attempt_request** | [**GitHubUserAttemptRequest**](GitHubUserAttemptRequest.md)|  | 

### Return type

[**GitHubUserConnectionSummary**](GitHubUserConnectionSummary.md)

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

# **personal_github_toolkit_v1_personal_github_connect**
> GitHubUserConnectOutput personal_github_toolkit_v1_personal_github_connect(toolkit_id, handle)

Personal Github Connect

Start exact-owner reviewed reconnect without replacing current credentials.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_connect_output import GitHubUserConnectOutput
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Github Connect
        api_response = api_instance.personal_github_toolkit_v1_personal_github_connect(toolkit_id, handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GitHubUserConnectOutput**](GitHubUserConnectOutput.md)

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

# **personal_github_toolkit_v1_personal_github_creation_app**
> GitHubSetupAppOutput personal_github_toolkit_v1_personal_github_creation_app(attempt_id, handle)

Personal Github Creation App

Observe actual selected App metadata without publishing the connection.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_setup_app_output import GitHubSetupAppOutput
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Github Creation App
        api_response = api_instance.personal_github_toolkit_v1_personal_github_creation_app(attempt_id, handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_app:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_app: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GitHubSetupAppOutput**](GitHubSetupAppOutput.md)

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

# **personal_github_toolkit_v1_personal_github_creation_cancel**
> personal_github_toolkit_v1_personal_github_creation_cancel(attempt_id, handle)

Personal Github Creation Cancel

Cancel only the initiating owner's unpublished personal credentials.

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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Github Creation Cancel
        api_instance.personal_github_toolkit_v1_personal_github_creation_cancel(attempt_id, handle)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
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

# **personal_github_toolkit_v1_personal_github_creation_confirm**
> GitHubUserCreatedOutput personal_github_toolkit_v1_personal_github_creation_confirm(handle, git_hub_user_creation_confirm_request)

Personal Github Creation Confirm

Publish canonical personal ownership after reviewed confirmation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_created_output import GitHubUserCreatedOutput
from azentspublicclient.models.git_hub_user_creation_confirm_request import GitHubUserCreationConfirmRequest
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    git_hub_user_creation_confirm_request = azentspublicclient.GitHubUserCreationConfirmRequest() # GitHubUserCreationConfirmRequest | 

    try:
        # Personal Github Creation Confirm
        api_response = api_instance.personal_github_toolkit_v1_personal_github_creation_confirm(handle, git_hub_user_creation_confirm_request)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **git_hub_user_creation_confirm_request** | [**GitHubUserCreationConfirmRequest**](GitHubUserCreationConfirmRequest.md)|  | 

### Return type

[**GitHubUserCreatedOutput**](GitHubUserCreatedOutput.md)

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

# **personal_github_toolkit_v1_personal_github_creation_connect**
> GitHubUserConnectOutput personal_github_toolkit_v1_personal_github_creation_connect(handle, personal_toolkit_create_request)

Personal Github Creation Connect

Authorize common GitHub settings before creating a personal Toolkit.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_connect_output import GitHubUserConnectOutput
from azentspublicclient.models.personal_toolkit_create_request import PersonalToolkitCreateRequest
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    personal_toolkit_create_request = azentspublicclient.PersonalToolkitCreateRequest() # PersonalToolkitCreateRequest | 

    try:
        # Personal Github Creation Connect
        api_response = api_instance.personal_github_toolkit_v1_personal_github_creation_connect(handle, personal_toolkit_create_request)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **personal_toolkit_create_request** | [**PersonalToolkitCreateRequest**](PersonalToolkitCreateRequest.md)|  | 

### Return type

[**GitHubUserConnectOutput**](GitHubUserConnectOutput.md)

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

# **personal_github_toolkit_v1_personal_github_creation_exchange**
> GitHubUserCreationReview personal_github_toolkit_v1_personal_github_creation_exchange(handle, git_hub_user_exchange_request)

Personal Github Creation Exchange

Stage verified account identity under exact personal setup authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_creation_review import GitHubUserCreationReview
from azentspublicclient.models.git_hub_user_exchange_request import GitHubUserExchangeRequest
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    git_hub_user_exchange_request = azentspublicclient.GitHubUserExchangeRequest() # GitHubUserExchangeRequest | 

    try:
        # Personal Github Creation Exchange
        api_response = api_instance.personal_github_toolkit_v1_personal_github_creation_exchange(handle, git_hub_user_exchange_request)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **git_hub_user_exchange_request** | [**GitHubUserExchangeRequest**](GitHubUserExchangeRequest.md)|  | 

### Return type

[**GitHubUserCreationReview**](GitHubUserCreationReview.md)

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

# **personal_github_toolkit_v1_personal_github_creation_review**
> GitHubUserCreationReview personal_github_toolkit_v1_personal_github_creation_review(attempt_id, handle)

Personal Github Creation Review

Read the common reviewed settings with explicit personal sharing scope.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_creation_review import GitHubUserCreationReview
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Github Creation Review
        api_response = api_instance.personal_github_toolkit_v1_personal_github_creation_review(attempt_id, handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_creation_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GitHubUserCreationReview**](GitHubUserCreationReview.md)

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

# **personal_github_toolkit_v1_personal_github_disconnect**
> personal_github_toolkit_v1_personal_github_disconnect(toolkit_id, handle)

Personal Github Disconnect

Remove local personal execution authority before bounded Provider cleanup.

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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Github Disconnect
        api_instance.personal_github_toolkit_v1_personal_github_disconnect(toolkit_id, handle)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_disconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
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

# **personal_github_toolkit_v1_personal_github_exchange**
> GitHubUserCandidateSummary personal_github_toolkit_v1_personal_github_exchange(toolkit_id, handle, git_hub_user_exchange_request)

Personal Github Exchange

Exchange only the initiating personal account and Auth Session's attempt.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_candidate_summary import GitHubUserCandidateSummary
from azentspublicclient.models.git_hub_user_exchange_request import GitHubUserExchangeRequest
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    git_hub_user_exchange_request = azentspublicclient.GitHubUserExchangeRequest() # GitHubUserExchangeRequest | 

    try:
        # Personal Github Exchange
        api_response = api_instance.personal_github_toolkit_v1_personal_github_exchange(toolkit_id, handle, git_hub_user_exchange_request)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **git_hub_user_exchange_request** | [**GitHubUserExchangeRequest**](GitHubUserExchangeRequest.md)|  | 

### Return type

[**GitHubUserCandidateSummary**](GitHubUserCandidateSummary.md)

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

# **personal_github_toolkit_v1_personal_github_install_url**
> GitHubPlatformInstallUrlResponse personal_github_toolkit_v1_personal_github_install_url(handle)

Personal Github Install Url

Open the same Platform App installation page after exact account admission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_platform_install_url_response import GitHubPlatformInstallUrlResponse
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Personal Github Install Url
        api_response = api_instance.personal_github_toolkit_v1_personal_github_install_url(handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_install_url:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_install_url: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GitHubPlatformInstallUrlResponse**](GitHubPlatformInstallUrlResponse.md)

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

# **personal_github_toolkit_v1_personal_github_installation_oauth_url**
> GitHubPlatformOAuthUrlResponse personal_github_toolkit_v1_personal_github_installation_oauth_url(handle)

Personal Github Installation Oauth Url

Start owner/Auth Session-bound Platform installation acquisition.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_platform_o_auth_url_response import GitHubPlatformOAuthUrlResponse
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Personal Github Installation Oauth Url
        api_response = api_instance.personal_github_toolkit_v1_personal_github_installation_oauth_url(handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_installation_oauth_url:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_installation_oauth_url: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GitHubPlatformOAuthUrlResponse**](GitHubPlatformOAuthUrlResponse.md)

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

# **personal_github_toolkit_v1_personal_github_review**
> GitHubUserCandidateSummary personal_github_toolkit_v1_personal_github_review(toolkit_id, handle, attempt_id)

Personal Github Review

Expose the same verified account metadata and explicit personal sharing scope.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_candidate_summary import GitHubUserCandidateSummary
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Personal Github Review
        api_response = api_instance.personal_github_toolkit_v1_personal_github_review(toolkit_id, handle, attempt_id)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **attempt_id** | **str**|  | 

### Return type

[**GitHubUserCandidateSummary**](GitHubUserCandidateSummary.md)

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

# **personal_github_toolkit_v1_personal_github_setup_app**
> GitHubSetupAppOutput personal_github_toolkit_v1_personal_github_setup_app(handle)

Personal Github Setup App

Observe the current Platform App after current-account personal admission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_setup_app_output import GitHubSetupAppOutput
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Personal Github Setup App
        api_response = api_instance.personal_github_toolkit_v1_personal_github_setup_app(handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_setup_app:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_setup_app: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GitHubSetupAppOutput**](GitHubSetupAppOutput.md)

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

# **personal_github_toolkit_v1_personal_github_setup_verify**
> GitHubSetupVerificationOutput personal_github_toolkit_v1_personal_github_setup_verify(handle, body)

Personal Github Setup Verify

Verify ordinary PAT/provided-App/Platform-App modes without publication.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.body import Body
from azentspublicclient.models.git_hub_setup_verification_output import GitHubSetupVerificationOutput
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    body = azentspublicclient.Body() # Body | 

    try:
        # Personal Github Setup Verify
        api_response = api_instance.personal_github_toolkit_v1_personal_github_setup_verify(handle, body)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_setup_verify:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_setup_verify: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **body** | [**Body**](Body.md)|  | 

### Return type

[**GitHubSetupVerificationOutput**](GitHubSetupVerificationOutput.md)

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

# **personal_github_toolkit_v1_personal_github_status**
> GitHubUserStatusOutput personal_github_toolkit_v1_personal_github_status(toolkit_id, handle)

Personal Github Status

Read current exact-owner grant identity without credential material.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_status_output import GitHubUserStatusOutput
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Github Status
        api_response = api_instance.personal_github_toolkit_v1_personal_github_status(toolkit_id, handle)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GitHubUserStatusOutput**](GitHubUserStatusOutput.md)

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

# **personal_github_toolkit_v1_personal_github_sync_installations**
> GitHubPlatformInstallationsResponse personal_github_toolkit_v1_personal_github_sync_installations(handle, personal_o_auth_exchange_request)

Personal Github Sync Installations

Publish the current owner's installation inventory, with no Toolkit creation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_platform_installations_response import GitHubPlatformInstallationsResponse
from azentspublicclient.models.personal_o_auth_exchange_request import PersonalOAuthExchangeRequest
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
    api_instance = azentspublicclient.PersonalGitHubToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    personal_o_auth_exchange_request = azentspublicclient.PersonalOAuthExchangeRequest() # PersonalOAuthExchangeRequest | 

    try:
        # Personal Github Sync Installations
        api_response = api_instance.personal_github_toolkit_v1_personal_github_sync_installations(handle, personal_o_auth_exchange_request)
        print("The response of PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_sync_installations:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGitHubToolkitV1Api->personal_github_toolkit_v1_personal_github_sync_installations: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **personal_o_auth_exchange_request** | [**PersonalOAuthExchangeRequest**](PersonalOAuthExchangeRequest.md)|  | 

### Return type

[**GitHubPlatformInstallationsResponse**](GitHubPlatformInstallationsResponse.md)

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

