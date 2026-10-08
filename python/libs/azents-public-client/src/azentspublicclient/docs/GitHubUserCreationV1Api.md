# azentspublicclient.GitHubUserCreationV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**github_user_creation_v1_agent_creation_cancel**](GitHubUserCreationV1Api.md#github_user_creation_v1_agent_creation_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github-user-creations/{attempt_id} | Agent Creation Cancel
[**github_user_creation_v1_agent_creation_confirm**](GitHubUserCreationV1Api.md#github_user_creation_v1_agent_creation_confirm) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github-user-creations/confirm | Agent Creation Confirm
[**github_user_creation_v1_agent_creation_connect**](GitHubUserCreationV1Api.md#github_user_creation_v1_agent_creation_connect) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github-user-creations/connect | Agent Creation Connect
[**github_user_creation_v1_agent_creation_exchange**](GitHubUserCreationV1Api.md#github_user_creation_v1_agent_creation_exchange) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github-user-creations/exchange | Agent Creation Exchange
[**github_user_creation_v1_agent_creation_review**](GitHubUserCreationV1Api.md#github_user_creation_v1_agent_creation_review) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github-user-creations/{attempt_id} | Agent Creation Review
[**github_user_creation_v1_shared_creation_cancel**](GitHubUserCreationV1Api.md#github_user_creation_v1_shared_creation_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/github-user-creations/{attempt_id} | Shared Creation Cancel
[**github_user_creation_v1_shared_creation_confirm**](GitHubUserCreationV1Api.md#github_user_creation_v1_shared_creation_confirm) | **POST** /toolkit/v1/workspaces/{handle}/github-user-creations/confirm | Shared Creation Confirm
[**github_user_creation_v1_shared_creation_connect**](GitHubUserCreationV1Api.md#github_user_creation_v1_shared_creation_connect) | **POST** /toolkit/v1/workspaces/{handle}/github-user-creations/connect | Shared Creation Connect
[**github_user_creation_v1_shared_creation_exchange**](GitHubUserCreationV1Api.md#github_user_creation_v1_shared_creation_exchange) | **POST** /toolkit/v1/workspaces/{handle}/github-user-creations/exchange | Shared Creation Exchange
[**github_user_creation_v1_shared_creation_review**](GitHubUserCreationV1Api.md#github_user_creation_v1_shared_creation_review) | **GET** /toolkit/v1/workspaces/{handle}/github-user-creations/{attempt_id} | Shared Creation Review


# **github_user_creation_v1_agent_creation_cancel**
> github_user_creation_v1_agent_creation_cancel(handle, agent_id, attempt_id)

Agent Creation Cancel

Cancel only this Agent's unpublished creation.

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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Agent Creation Cancel
        api_instance.github_user_creation_v1_agent_creation_cancel(handle, agent_id, attempt_id)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **attempt_id** | **str**|  | 

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

# **github_user_creation_v1_agent_creation_confirm**
> GitHubUserCreatedOutput github_user_creation_v1_agent_creation_confirm(handle, agent_id, git_hub_user_attempt_request)

Agent Creation Confirm

Publish Toolkit, namespace and current account together.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_attempt_request import GitHubUserAttemptRequest
from azentspublicclient.models.git_hub_user_created_output import GitHubUserCreatedOutput
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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Agent Creation Confirm
        api_response = api_instance.github_user_creation_v1_agent_creation_confirm(handle, agent_id, git_hub_user_attempt_request)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **git_hub_user_attempt_request** | [**GitHubUserAttemptRequest**](GitHubUserAttemptRequest.md)|  | 

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

# **github_user_creation_v1_agent_creation_connect**
> GitHubUserConnectOutput github_user_creation_v1_agent_creation_connect(handle, agent_id, toolkit_config_create_request)

Agent Creation Connect

Start unpublished creation within exact Agent management authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_connect_output import GitHubUserConnectOutput
from azentspublicclient.models.toolkit_config_create_request import ToolkitConfigCreateRequest
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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    toolkit_config_create_request = azentspublicclient.ToolkitConfigCreateRequest() # ToolkitConfigCreateRequest | 

    try:
        # Agent Creation Connect
        api_response = api_instance.github_user_creation_v1_agent_creation_connect(handle, agent_id, toolkit_config_create_request)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **toolkit_config_create_request** | [**ToolkitConfigCreateRequest**](ToolkitConfigCreateRequest.md)|  | 

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

# **github_user_creation_v1_agent_creation_exchange**
> GitHubUserCreationReview github_user_creation_v1_agent_creation_exchange(handle, agent_id, git_hub_user_exchange_request)

Agent Creation Exchange

Review only the initiating Agent-owned creation context.

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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    git_hub_user_exchange_request = azentspublicclient.GitHubUserExchangeRequest() # GitHubUserExchangeRequest | 

    try:
        # Agent Creation Exchange
        api_response = api_instance.github_user_creation_v1_agent_creation_exchange(handle, agent_id, git_hub_user_exchange_request)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
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

# **github_user_creation_v1_agent_creation_review**
> GitHubUserCreationReview github_user_creation_v1_agent_creation_review(handle, agent_id, attempt_id)

Agent Creation Review

Resume only this initiating Agent creation.

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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Agent Creation Review
        api_response = api_instance.github_user_creation_v1_agent_creation_review(handle, agent_id, attempt_id)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_agent_creation_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **attempt_id** | **str**|  | 

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

# **github_user_creation_v1_shared_creation_cancel**
> github_user_creation_v1_shared_creation_cancel(handle, attempt_id)

Shared Creation Cancel

Cancel unpublished creation and await exact fail-open token cleanup.

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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Shared Creation Cancel
        api_instance.github_user_creation_v1_shared_creation_cancel(handle, attempt_id)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **attempt_id** | **str**|  | 

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

# **github_user_creation_v1_shared_creation_confirm**
> GitHubUserCreatedOutput github_user_creation_v1_shared_creation_confirm(handle, git_hub_user_attempt_request)

Shared Creation Confirm

Atomically create a shared Toolkit and its confirmed account.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_attempt_request import GitHubUserAttemptRequest
from azentspublicclient.models.git_hub_user_created_output import GitHubUserCreatedOutput
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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    git_hub_user_attempt_request = azentspublicclient.GitHubUserAttemptRequest() # GitHubUserAttemptRequest | 

    try:
        # Shared Creation Confirm
        api_response = api_instance.github_user_creation_v1_shared_creation_confirm(handle, git_hub_user_attempt_request)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **git_hub_user_attempt_request** | [**GitHubUserAttemptRequest**](GitHubUserAttemptRequest.md)|  | 

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

# **github_user_creation_v1_shared_creation_connect**
> GitHubUserConnectOutput github_user_creation_v1_shared_creation_connect(handle, toolkit_config_create_request)

Shared Creation Connect

Authorize desired settings without creating a saved Toolkit.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_user_connect_output import GitHubUserConnectOutput
from azentspublicclient.models.toolkit_config_create_request import ToolkitConfigCreateRequest
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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    toolkit_config_create_request = azentspublicclient.ToolkitConfigCreateRequest() # ToolkitConfigCreateRequest | 

    try:
        # Shared Creation Connect
        api_response = api_instance.github_user_creation_v1_shared_creation_connect(handle, toolkit_config_create_request)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **toolkit_config_create_request** | [**ToolkitConfigCreateRequest**](ToolkitConfigCreateRequest.md)|  | 

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

# **github_user_creation_v1_shared_creation_exchange**
> GitHubUserCreationReview github_user_creation_v1_shared_creation_exchange(handle, git_hub_user_exchange_request)

Shared Creation Exchange

Exchange once and stage identity without publishing configuration.

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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    git_hub_user_exchange_request = azentspublicclient.GitHubUserExchangeRequest() # GitHubUserExchangeRequest | 

    try:
        # Shared Creation Exchange
        api_response = api_instance.github_user_creation_v1_shared_creation_exchange(handle, git_hub_user_exchange_request)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_exchange: %s\n" % e)
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

# **github_user_creation_v1_shared_creation_review**
> GitHubUserCreationReview github_user_creation_v1_shared_creation_review(handle, attempt_id)

Shared Creation Review

Read desired nonsecret settings and verified account for confirmation.

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
    api_instance = azentspublicclient.GitHubUserCreationV1Api(api_client)
    handle = 'handle_example' # str | 
    attempt_id = 'attempt_id_example' # str | 

    try:
        # Shared Creation Review
        api_response = api_instance.github_user_creation_v1_shared_creation_review(handle, attempt_id)
        print("The response of GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubUserCreationV1Api->github_user_creation_v1_shared_creation_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **attempt_id** | **str**|  | 

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

