# azentspublicclient.GitHubUserToolkitV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**github_user_toolkit_v1_agent_access**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_access) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/access | Agent Access
[**github_user_toolkit_v1_agent_cancel**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/attempt | Agent Cancel
[**github_user_toolkit_v1_agent_confirm**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_confirm) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/confirm | Agent Confirm
[**github_user_toolkit_v1_agent_connect**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_connect) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/connect | Agent Connect
[**github_user_toolkit_v1_agent_disconnect**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_disconnect) | **DELETE** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/connection | Agent Disconnect
[**github_user_toolkit_v1_agent_exchange**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_exchange) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/exchange | Agent Exchange
[**github_user_toolkit_v1_agent_review**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_review) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/attempts/{attempt_id} | Agent Review
[**github_user_toolkit_v1_agent_setup_availability**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_setup_availability) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github/setup-availability | Agent Setup Availability
[**github_user_toolkit_v1_agent_status**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_agent_status) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/github-user/status | Agent Status
[**github_user_toolkit_v1_shared_access**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_access) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/access | Shared Access
[**github_user_toolkit_v1_shared_cancel**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/attempt | Shared Cancel
[**github_user_toolkit_v1_shared_confirm**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_confirm) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/confirm | Shared Confirm
[**github_user_toolkit_v1_shared_connect**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_connect) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/connect | Shared Connect
[**github_user_toolkit_v1_shared_disconnect**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_disconnect) | **DELETE** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/connection | Shared Disconnect
[**github_user_toolkit_v1_shared_exchange**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_exchange) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/exchange | Shared Exchange
[**github_user_toolkit_v1_shared_review**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_review) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/attempts/{attempt_id} | Shared Review
[**github_user_toolkit_v1_shared_setup_availability**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_setup_availability) | **GET** /toolkit/v1/workspaces/{handle}/github/setup-availability | Shared Setup Availability
[**github_user_toolkit_v1_shared_status**](GitHubUserToolkitV1Api.md#github_user_toolkit_v1_shared_status) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/github-user/status | Shared Status


# **github_user_toolkit_v1_agent_access**
> GitHubUserAccessPage github_user_toolkit_v1_agent_access(handle, agent_id, toolkit_id, cursor=cursor)

Agent Access

Observe multi-owner readiness without granting participant list access.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    cursor = 'cursor_example' # str |  (optional)

    try:
        # Agent Access
        api_response = api_instance.github_user_toolkit_v1_agent_access(handle, agent_id, toolkit_id, cursor=cursor)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_agent_cancel**
> github_user_toolkit_v1_agent_cancel(handle, agent_id, toolkit_id, git_hub_user_attempt_request)

Agent Cancel

Cancel only this Agent-owned setup attempt.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Agent Cancel
        api_instance.github_user_toolkit_v1_agent_cancel(handle, agent_id, toolkit_id, git_hub_user_attempt_request)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_agent_confirm**
> GitHubUserConnectionSummary github_user_toolkit_v1_agent_confirm(handle, agent_id, toolkit_id, git_hub_user_attempt_request)

Agent Confirm

Confirm account replacement within the exact Agent-owned Toolkit.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Agent Confirm
        api_response = api_instance.github_user_toolkit_v1_agent_confirm(handle, agent_id, toolkit_id, git_hub_user_attempt_request)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_agent_connect**
> GitHubUserConnectOutput github_user_toolkit_v1_agent_connect(handle, agent_id, toolkit_id)

Agent Connect

Start setup for a Toolkit owned by this exact managed Agent.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Agent Connect
        api_response = api_instance.github_user_toolkit_v1_agent_connect(handle, agent_id, toolkit_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 

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

# **github_user_toolkit_v1_agent_disconnect**
> github_user_toolkit_v1_agent_disconnect(handle, agent_id, toolkit_id)

Agent Disconnect

Disconnect the exact Agent-owned credential without affecting attachments.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Agent Disconnect
        api_instance.github_user_toolkit_v1_agent_disconnect(handle, agent_id, toolkit_id)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_disconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 

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

# **github_user_toolkit_v1_agent_exchange**
> GitHubUserCandidateSummary github_user_toolkit_v1_agent_exchange(handle, agent_id, toolkit_id, git_hub_user_exchange_request)

Agent Exchange

Consume one callback without changing the existing Agent-owned credential.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    git_hub_user_exchange_request = azentspublicclient.GitHubUserExchangeRequest() # GitHubUserExchangeRequest | 

    try:
        # Agent Exchange
        api_response = api_instance.github_user_toolkit_v1_agent_exchange(handle, agent_id, toolkit_id, git_hub_user_exchange_request)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_agent_review**
> GitHubUserCandidateSummary github_user_toolkit_v1_agent_review(handle, agent_id, toolkit_id, attempt_id)

Agent Review

Read verified account/use scope after exact popup completion notification.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Agent Review
        api_response = api_instance.github_user_toolkit_v1_agent_review(handle, agent_id, toolkit_id, attempt_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_agent_setup_availability**
> GitHubSetupAvailability github_user_toolkit_v1_agent_setup_availability(handle, agent_id)

Agent Setup Availability

Return local registration availability only to an Agent manager.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 

    try:
        # Agent Setup Availability
        api_response = api_instance.github_user_toolkit_v1_agent_setup_availability(handle, agent_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_setup_availability:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_setup_availability: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 

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

# **github_user_toolkit_v1_agent_status**
> GitHubUserStatusOutput github_user_toolkit_v1_agent_status(handle, agent_id, toolkit_id)

Agent Status

Return connection details only within exact Agent management scope.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Agent Status
        api_response = api_instance.github_user_toolkit_v1_agent_status(handle, agent_id, toolkit_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_agent_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 

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

# **github_user_toolkit_v1_shared_access**
> GitHubUserAccessPage github_user_toolkit_v1_shared_access(handle, toolkit_id, cursor=cursor)

Shared Access

Observe bounded personal and organization readiness for this account/App.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    cursor = 'cursor_example' # str |  (optional)

    try:
        # Shared Access
        api_response = api_instance.github_user_toolkit_v1_shared_access(handle, toolkit_id, cursor=cursor)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_shared_cancel**
> github_user_toolkit_v1_shared_cancel(handle, toolkit_id, git_hub_user_attempt_request)

Shared Cancel

Cancel the initiating shared setup and revoke any issued candidate.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Shared Cancel
        api_instance.github_user_toolkit_v1_shared_cancel(handle, toolkit_id, git_hub_user_attempt_request)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_shared_confirm**
> GitHubUserConnectionSummary github_user_toolkit_v1_shared_confirm(handle, toolkit_id, git_hub_user_attempt_request)

Shared Confirm

Explicitly activate reviewed account and sharing scope.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Shared Confirm
        api_response = api_instance.github_user_toolkit_v1_shared_confirm(handle, toolkit_id, git_hub_user_attempt_request)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_shared_connect**
> GitHubUserConnectOutput github_user_toolkit_v1_shared_connect(handle, toolkit_id)

Shared Connect

Start one bound shared-Toolkit authorization without replacing credentials.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Shared Connect
        api_response = api_instance.github_user_toolkit_v1_shared_connect(handle, toolkit_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 

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

# **github_user_toolkit_v1_shared_disconnect**
> github_user_toolkit_v1_shared_disconnect(handle, toolkit_id)

Shared Disconnect

Disconnect local shared use and attempt bounded token revocation.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Shared Disconnect
        api_instance.github_user_toolkit_v1_shared_disconnect(handle, toolkit_id)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_disconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 

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

# **github_user_toolkit_v1_shared_exchange**
> GitHubUserCandidateSummary github_user_toolkit_v1_shared_exchange(handle, toolkit_id, git_hub_user_exchange_request)

Shared Exchange

Stage verified account identity for the same shared setup context.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    git_hub_user_exchange_request = azentspublicclient.GitHubUserExchangeRequest() # GitHubUserExchangeRequest | 

    try:
        # Shared Exchange
        api_response = api_instance.github_user_toolkit_v1_shared_exchange(handle, toolkit_id, git_hub_user_exchange_request)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_shared_review**
> GitHubUserCandidateSummary github_user_toolkit_v1_shared_review(handle, toolkit_id, attempt_id)

Shared Review

Read current review identity from the originating shared setup.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Shared Review
        api_response = api_instance.github_user_toolkit_v1_shared_review(handle, toolkit_id, attempt_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 
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

# **github_user_toolkit_v1_shared_setup_availability**
> GitHubSetupAvailability github_user_toolkit_v1_shared_setup_availability(handle)

Shared Setup Availability

Return local Platform registration availability for shared setup.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Shared Setup Availability
        api_response = api_instance.github_user_toolkit_v1_shared_setup_availability(handle)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_setup_availability:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_setup_availability: %s\n" % e)
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

# **github_user_toolkit_v1_shared_status**
> GitHubUserStatusOutput github_user_toolkit_v1_shared_status(handle, toolkit_id)

Shared Status

Return redacted saved identity without asserting provider cleanup.

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
    api_instance = azentspublicclient.GitHubUserToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Shared Status
        api_response = api_instance.github_user_toolkit_v1_shared_status(handle, toolkit_id)
        print("The response of GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserToolkitV1Api->github_user_toolkit_v1_shared_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_id** | **str**|  | 

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

