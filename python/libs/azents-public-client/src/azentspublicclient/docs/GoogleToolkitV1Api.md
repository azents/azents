# azentspublicclient.GoogleToolkitV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**google_toolkit_v1_agent_google_cancel**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id} | Agent Google Cancel
[**google_toolkit_v1_agent_google_confirm**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_confirm) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}/confirm | Agent Google Confirm
[**google_toolkit_v1_agent_google_connect**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_connect) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/connect | Agent Google Connect
[**google_toolkit_v1_agent_google_disconnect**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_disconnect) | **DELETE** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/connection | Agent Google Disconnect
[**google_toolkit_v1_agent_google_exchange**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_exchange) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/exchange | Agent Google Exchange
[**google_toolkit_v1_agent_google_outcome**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_outcome) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}/outcome | Agent Google Outcome
[**google_toolkit_v1_agent_google_picker_token**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_picker_token) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/picker-token | Agent Google Picker Token
[**google_toolkit_v1_agent_google_preparation**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_preparation) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/preparation | Agent Google Preparation
[**google_toolkit_v1_agent_google_reconnect**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_reconnect) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/reconnect | Agent Google Reconnect
[**google_toolkit_v1_agent_google_reconnect_confirm**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_reconnect_confirm) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id}/reconnect-confirm | Agent Google Reconnect Confirm
[**google_toolkit_v1_agent_google_review**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_review) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/google/attempts/{attempt_id} | Agent Google Review
[**google_toolkit_v1_agent_google_services**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_services) | **PATCH** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/services | Agent Google Services
[**google_toolkit_v1_agent_google_status**](GoogleToolkitV1Api.md#google_toolkit_v1_agent_google_status) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/toolkit-configs/{toolkit_id}/google/connection | Agent Google Status
[**google_toolkit_v1_shared_google_cancel**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/google/attempts/{attempt_id} | Shared Google Cancel
[**google_toolkit_v1_shared_google_confirm**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_confirm) | **POST** /toolkit/v1/workspaces/{handle}/google/attempts/{attempt_id}/confirm | Shared Google Confirm
[**google_toolkit_v1_shared_google_connect**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_connect) | **POST** /toolkit/v1/workspaces/{handle}/google/connect | Shared Google Connect
[**google_toolkit_v1_shared_google_disconnect**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_disconnect) | **DELETE** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/connection | Shared Google Disconnect
[**google_toolkit_v1_shared_google_exchange**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_exchange) | **POST** /toolkit/v1/workspaces/{handle}/google/exchange | Shared Google Exchange
[**google_toolkit_v1_shared_google_outcome**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_outcome) | **GET** /toolkit/v1/workspaces/{handle}/google/attempts/{attempt_id}/outcome | Shared Google Outcome
[**google_toolkit_v1_shared_google_picker_token**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_picker_token) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/picker-token | Shared Google Picker Token
[**google_toolkit_v1_shared_google_preparation**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_preparation) | **GET** /toolkit/v1/workspaces/{handle}/google/preparation | Shared Google Preparation
[**google_toolkit_v1_shared_google_reconnect**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_reconnect) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/reconnect | Shared Google Reconnect
[**google_toolkit_v1_shared_google_reconnect_confirm**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_reconnect_confirm) | **POST** /toolkit/v1/workspaces/{handle}/google/attempts/{attempt_id}/reconnect-confirm | Shared Google Reconnect Confirm
[**google_toolkit_v1_shared_google_review**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_review) | **GET** /toolkit/v1/workspaces/{handle}/google/attempts/{attempt_id} | Shared Google Review
[**google_toolkit_v1_shared_google_services**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_services) | **PATCH** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/services | Shared Google Services
[**google_toolkit_v1_shared_google_status**](GoogleToolkitV1Api.md#google_toolkit_v1_shared_google_status) | **GET** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_id}/google/connection | Shared Google Status


# **google_toolkit_v1_agent_google_cancel**
> GoogleCancelOutput google_toolkit_v1_agent_google_cancel(attempt_id, agent_id, handle)

Agent Google Cancel

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_cancel_output import GoogleCancelOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Agent Google Cancel
        api_response = api_instance.google_toolkit_v1_agent_google_cancel(attempt_id, agent_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_cancel:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleCancelOutput**](GoogleCancelOutput.md)

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

# **google_toolkit_v1_agent_google_confirm**
> GooglePublishedOutput google_toolkit_v1_agent_google_confirm(attempt_id, agent_id, handle, google_confirm_request)

Agent Google Confirm

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_confirm_request import GoogleConfirmRequest
from azentspublicclient.models.google_published_output import GooglePublishedOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    google_confirm_request = azentspublicclient.GoogleConfirmRequest() # GoogleConfirmRequest | 

    try:
        # Agent Google Confirm
        api_response = api_instance.google_toolkit_v1_agent_google_confirm(attempt_id, agent_id, handle, google_confirm_request)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_confirm_request** | [**GoogleConfirmRequest**](GoogleConfirmRequest.md)|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **google_toolkit_v1_agent_google_connect**
> GoogleConnectOutput google_toolkit_v1_agent_google_connect(agent_id, handle, google_connect_input)

Agent Google Connect

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connect_input import GoogleConnectInput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    google_connect_input = azentspublicclient.GoogleConnectInput() # GoogleConnectInput | 

    try:
        # Agent Google Connect
        api_response = api_instance.google_toolkit_v1_agent_google_connect(agent_id, handle, google_connect_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_connect_input** | [**GoogleConnectInput**](GoogleConnectInput.md)|  | 

### Return type

[**GoogleConnectOutput**](GoogleConnectOutput.md)

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

# **google_toolkit_v1_agent_google_disconnect**
> object google_toolkit_v1_agent_google_disconnect(toolkit_id, agent_id, handle)

Agent Google Disconnect

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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Agent Google Disconnect
        api_response = api_instance.google_toolkit_v1_agent_google_disconnect(toolkit_id, agent_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_disconnect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_disconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

**object**

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

# **google_toolkit_v1_agent_google_exchange**
> GoogleReview google_toolkit_v1_agent_google_exchange(agent_id, handle, google_exchange_request)

Agent Google Exchange

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_exchange_request import GoogleExchangeRequest
from azentspublicclient.models.google_review import GoogleReview
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    google_exchange_request = azentspublicclient.GoogleExchangeRequest() # GoogleExchangeRequest | 

    try:
        # Agent Google Exchange
        api_response = api_instance.google_toolkit_v1_agent_google_exchange(agent_id, handle, google_exchange_request)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_exchange_request** | [**GoogleExchangeRequest**](GoogleExchangeRequest.md)|  | 

### Return type

[**GoogleReview**](GoogleReview.md)

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

# **google_toolkit_v1_agent_google_outcome**
> GooglePublishedOutput google_toolkit_v1_agent_google_outcome(attempt_id, agent_id, handle)

Agent Google Outcome

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_published_output import GooglePublishedOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Agent Google Outcome
        api_response = api_instance.google_toolkit_v1_agent_google_outcome(attempt_id, agent_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_outcome:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_outcome: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **google_toolkit_v1_agent_google_picker_token**
> GooglePickerTokenOutput google_toolkit_v1_agent_google_picker_token(toolkit_id, agent_id, handle, google_picker_token_input)

Agent Google Picker Token

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_picker_token_input import GooglePickerTokenInput
from azentspublicclient.models.google_picker_token_output import GooglePickerTokenOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    google_picker_token_input = azentspublicclient.GooglePickerTokenInput() # GooglePickerTokenInput | 

    try:
        # Agent Google Picker Token
        api_response = api_instance.google_toolkit_v1_agent_google_picker_token(toolkit_id, agent_id, handle, google_picker_token_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_picker_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_picker_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_picker_token_input** | [**GooglePickerTokenInput**](GooglePickerTokenInput.md)|  | 

### Return type

[**GooglePickerTokenOutput**](GooglePickerTokenOutput.md)

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

# **google_toolkit_v1_agent_google_preparation**
> GooglePreparation google_toolkit_v1_agent_google_preparation(agent_id, handle)

Agent Google Preparation

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_preparation import GooglePreparation
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Agent Google Preparation
        api_response = api_instance.google_toolkit_v1_agent_google_preparation(agent_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_preparation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_preparation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GooglePreparation**](GooglePreparation.md)

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

# **google_toolkit_v1_agent_google_reconnect**
> GoogleConnectOutput google_toolkit_v1_agent_google_reconnect(agent_id, toolkit_id, handle, google_connect_input)

Agent Google Reconnect

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connect_input import GoogleConnectInput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    google_connect_input = azentspublicclient.GoogleConnectInput() # GoogleConnectInput | 

    try:
        # Agent Google Reconnect
        api_response = api_instance.google_toolkit_v1_agent_google_reconnect(agent_id, toolkit_id, handle, google_connect_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_reconnect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_reconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_connect_input** | [**GoogleConnectInput**](GoogleConnectInput.md)|  | 

### Return type

[**GoogleConnectOutput**](GoogleConnectOutput.md)

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

# **google_toolkit_v1_agent_google_reconnect_confirm**
> GooglePublishedOutput google_toolkit_v1_agent_google_reconnect_confirm(attempt_id, agent_id, handle, google_reconnect_confirm_request)

Agent Google Reconnect Confirm

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.models.google_reconnect_confirm_request import GoogleReconnectConfirmRequest
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    google_reconnect_confirm_request = azentspublicclient.GoogleReconnectConfirmRequest() # GoogleReconnectConfirmRequest | 

    try:
        # Agent Google Reconnect Confirm
        api_response = api_instance.google_toolkit_v1_agent_google_reconnect_confirm(attempt_id, agent_id, handle, google_reconnect_confirm_request)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_reconnect_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_reconnect_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_reconnect_confirm_request** | [**GoogleReconnectConfirmRequest**](GoogleReconnectConfirmRequest.md)|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **google_toolkit_v1_agent_google_review**
> GoogleReview google_toolkit_v1_agent_google_review(attempt_id, agent_id, handle)

Agent Google Review

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_review import GoogleReview
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Agent Google Review
        api_response = api_instance.google_toolkit_v1_agent_google_review(attempt_id, agent_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleReview**](GoogleReview.md)

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

# **google_toolkit_v1_agent_google_services**
> GoogleConnectionOutput google_toolkit_v1_agent_google_services(toolkit_id, agent_id, handle, google_services_update_input)

Agent Google Services

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
from azentspublicclient.models.google_services_update_input import GoogleServicesUpdateInput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    google_services_update_input = azentspublicclient.GoogleServicesUpdateInput() # GoogleServicesUpdateInput | 

    try:
        # Agent Google Services
        api_response = api_instance.google_toolkit_v1_agent_google_services(toolkit_id, agent_id, handle, google_services_update_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_services:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_services: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_services_update_input** | [**GoogleServicesUpdateInput**](GoogleServicesUpdateInput.md)|  | 

### Return type

[**GoogleConnectionOutput**](GoogleConnectionOutput.md)

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

# **google_toolkit_v1_agent_google_status**
> GoogleConnectionOutput google_toolkit_v1_agent_google_status(toolkit_id, agent_id, handle)

Agent Google Status

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Agent Google Status
        api_response = api_instance.google_toolkit_v1_agent_google_status(toolkit_id, agent_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_agent_google_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_agent_google_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleConnectionOutput**](GoogleConnectionOutput.md)

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

# **google_toolkit_v1_shared_google_cancel**
> GoogleCancelOutput google_toolkit_v1_shared_google_cancel(attempt_id, handle)

Shared Google Cancel

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_cancel_output import GoogleCancelOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Shared Google Cancel
        api_response = api_instance.google_toolkit_v1_shared_google_cancel(attempt_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_cancel:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleCancelOutput**](GoogleCancelOutput.md)

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

# **google_toolkit_v1_shared_google_confirm**
> GooglePublishedOutput google_toolkit_v1_shared_google_confirm(attempt_id, handle, google_confirm_request)

Shared Google Confirm

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_confirm_request import GoogleConfirmRequest
from azentspublicclient.models.google_published_output import GooglePublishedOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 
    google_confirm_request = azentspublicclient.GoogleConfirmRequest() # GoogleConfirmRequest | 

    try:
        # Shared Google Confirm
        api_response = api_instance.google_toolkit_v1_shared_google_confirm(attempt_id, handle, google_confirm_request)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_confirm_request** | [**GoogleConfirmRequest**](GoogleConfirmRequest.md)|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **google_toolkit_v1_shared_google_connect**
> GoogleConnectOutput google_toolkit_v1_shared_google_connect(handle, google_connect_input)

Shared Google Connect

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connect_input import GoogleConnectInput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    google_connect_input = azentspublicclient.GoogleConnectInput() # GoogleConnectInput | 

    try:
        # Shared Google Connect
        api_response = api_instance.google_toolkit_v1_shared_google_connect(handle, google_connect_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **google_connect_input** | [**GoogleConnectInput**](GoogleConnectInput.md)|  | 

### Return type

[**GoogleConnectOutput**](GoogleConnectOutput.md)

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

# **google_toolkit_v1_shared_google_disconnect**
> object google_toolkit_v1_shared_google_disconnect(toolkit_id, handle)

Shared Google Disconnect

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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Shared Google Disconnect
        api_response = api_instance.google_toolkit_v1_shared_google_disconnect(toolkit_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_disconnect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_disconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

**object**

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

# **google_toolkit_v1_shared_google_exchange**
> GoogleReview google_toolkit_v1_shared_google_exchange(handle, google_exchange_request)

Shared Google Exchange

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_exchange_request import GoogleExchangeRequest
from azentspublicclient.models.google_review import GoogleReview
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    google_exchange_request = azentspublicclient.GoogleExchangeRequest() # GoogleExchangeRequest | 

    try:
        # Shared Google Exchange
        api_response = api_instance.google_toolkit_v1_shared_google_exchange(handle, google_exchange_request)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **google_exchange_request** | [**GoogleExchangeRequest**](GoogleExchangeRequest.md)|  | 

### Return type

[**GoogleReview**](GoogleReview.md)

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

# **google_toolkit_v1_shared_google_outcome**
> GooglePublishedOutput google_toolkit_v1_shared_google_outcome(attempt_id, handle)

Shared Google Outcome

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_published_output import GooglePublishedOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Shared Google Outcome
        api_response = api_instance.google_toolkit_v1_shared_google_outcome(attempt_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_outcome:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_outcome: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **google_toolkit_v1_shared_google_picker_token**
> GooglePickerTokenOutput google_toolkit_v1_shared_google_picker_token(toolkit_id, handle, google_picker_token_input)

Shared Google Picker Token

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_picker_token_input import GooglePickerTokenInput
from azentspublicclient.models.google_picker_token_output import GooglePickerTokenOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    google_picker_token_input = azentspublicclient.GooglePickerTokenInput() # GooglePickerTokenInput | 

    try:
        # Shared Google Picker Token
        api_response = api_instance.google_toolkit_v1_shared_google_picker_token(toolkit_id, handle, google_picker_token_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_picker_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_picker_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_picker_token_input** | [**GooglePickerTokenInput**](GooglePickerTokenInput.md)|  | 

### Return type

[**GooglePickerTokenOutput**](GooglePickerTokenOutput.md)

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

# **google_toolkit_v1_shared_google_preparation**
> GooglePreparation google_toolkit_v1_shared_google_preparation(handle)

Shared Google Preparation

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_preparation import GooglePreparation
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Shared Google Preparation
        api_response = api_instance.google_toolkit_v1_shared_google_preparation(handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_preparation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_preparation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GooglePreparation**](GooglePreparation.md)

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

# **google_toolkit_v1_shared_google_reconnect**
> GoogleConnectOutput google_toolkit_v1_shared_google_reconnect(toolkit_id, handle, google_connect_input)

Shared Google Reconnect

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connect_input import GoogleConnectInput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    google_connect_input = azentspublicclient.GoogleConnectInput() # GoogleConnectInput | 

    try:
        # Shared Google Reconnect
        api_response = api_instance.google_toolkit_v1_shared_google_reconnect(toolkit_id, handle, google_connect_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_reconnect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_reconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_connect_input** | [**GoogleConnectInput**](GoogleConnectInput.md)|  | 

### Return type

[**GoogleConnectOutput**](GoogleConnectOutput.md)

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

# **google_toolkit_v1_shared_google_reconnect_confirm**
> GooglePublishedOutput google_toolkit_v1_shared_google_reconnect_confirm(attempt_id, handle, google_reconnect_confirm_request)

Shared Google Reconnect Confirm

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.models.google_reconnect_confirm_request import GoogleReconnectConfirmRequest
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 
    google_reconnect_confirm_request = azentspublicclient.GoogleReconnectConfirmRequest() # GoogleReconnectConfirmRequest | 

    try:
        # Shared Google Reconnect Confirm
        api_response = api_instance.google_toolkit_v1_shared_google_reconnect_confirm(attempt_id, handle, google_reconnect_confirm_request)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_reconnect_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_reconnect_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_reconnect_confirm_request** | [**GoogleReconnectConfirmRequest**](GoogleReconnectConfirmRequest.md)|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **google_toolkit_v1_shared_google_review**
> GoogleReview google_toolkit_v1_shared_google_review(attempt_id, handle)

Shared Google Review

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_review import GoogleReview
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Shared Google Review
        api_response = api_instance.google_toolkit_v1_shared_google_review(attempt_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleReview**](GoogleReview.md)

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

# **google_toolkit_v1_shared_google_services**
> GoogleConnectionOutput google_toolkit_v1_shared_google_services(toolkit_id, handle, google_services_update_input)

Shared Google Services

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
from azentspublicclient.models.google_services_update_input import GoogleServicesUpdateInput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    google_services_update_input = azentspublicclient.GoogleServicesUpdateInput() # GoogleServicesUpdateInput | 

    try:
        # Shared Google Services
        api_response = api_instance.google_toolkit_v1_shared_google_services(toolkit_id, handle, google_services_update_input)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_services:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_services: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_services_update_input** | [**GoogleServicesUpdateInput**](GoogleServicesUpdateInput.md)|  | 

### Return type

[**GoogleConnectionOutput**](GoogleConnectionOutput.md)

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

# **google_toolkit_v1_shared_google_status**
> GoogleConnectionOutput google_toolkit_v1_shared_google_status(toolkit_id, handle)

Shared Google Status

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
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
    api_instance = azentspublicclient.GoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Shared Google Status
        api_response = api_instance.google_toolkit_v1_shared_google_status(toolkit_id, handle)
        print("The response of GoogleToolkitV1Api->google_toolkit_v1_shared_google_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GoogleToolkitV1Api->google_toolkit_v1_shared_google_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleConnectionOutput**](GoogleConnectionOutput.md)

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

