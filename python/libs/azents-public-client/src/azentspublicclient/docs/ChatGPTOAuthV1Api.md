# azentspublicclient.ChatGPTOAuthV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**chatgpt_oauth_v1_cancel_device**](ChatGPTOAuthV1Api.md#chatgpt_oauth_v1_cancel_device) | **DELETE** /llm-provider-integration/v1/workspaces/{handle}/chatgpt-oauth/device/{session_id} | Cancel Device
[**chatgpt_oauth_v1_poll_device**](ChatGPTOAuthV1Api.md#chatgpt_oauth_v1_poll_device) | **GET** /llm-provider-integration/v1/workspaces/{handle}/chatgpt-oauth/device/{session_id} | Poll Device
[**chatgpt_oauth_v1_start_device**](ChatGPTOAuthV1Api.md#chatgpt_oauth_v1_start_device) | **POST** /llm-provider-integration/v1/workspaces/{handle}/chatgpt-oauth/device/start | Start Device


# **chatgpt_oauth_v1_cancel_device**
> ChatGPTOAuthDeviceStatusResponse chatgpt_oauth_v1_cancel_device(session_id, handle)

Cancel Device

Cancel ChatGPT OAuth device flow.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_gpto_auth_device_status_response import ChatGPTOAuthDeviceStatusResponse
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
    api_instance = azentspublicclient.ChatGPTOAuthV1Api(api_client)
    session_id = 'session_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Cancel Device
        api_response = api_instance.chatgpt_oauth_v1_cancel_device(session_id, handle)
        print("The response of ChatGPTOAuthV1Api->chatgpt_oauth_v1_cancel_device:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatGPTOAuthV1Api->chatgpt_oauth_v1_cancel_device: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ChatGPTOAuthDeviceStatusResponse**](ChatGPTOAuthDeviceStatusResponse.md)

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

# **chatgpt_oauth_v1_poll_device**
> ChatGPTOAuthDeviceStatusResponse chatgpt_oauth_v1_poll_device(session_id, handle)

Poll Device

Poll ChatGPT OAuth device flow status once.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_gpto_auth_device_status_response import ChatGPTOAuthDeviceStatusResponse
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
    api_instance = azentspublicclient.ChatGPTOAuthV1Api(api_client)
    session_id = 'session_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Poll Device
        api_response = api_instance.chatgpt_oauth_v1_poll_device(session_id, handle)
        print("The response of ChatGPTOAuthV1Api->chatgpt_oauth_v1_poll_device:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatGPTOAuthV1Api->chatgpt_oauth_v1_poll_device: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ChatGPTOAuthDeviceStatusResponse**](ChatGPTOAuthDeviceStatusResponse.md)

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

# **chatgpt_oauth_v1_start_device**
> ChatGPTOAuthDeviceStartResponse chatgpt_oauth_v1_start_device(handle)

Start Device

Start ChatGPT OAuth device flow.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_gpto_auth_device_start_response import ChatGPTOAuthDeviceStartResponse
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
    api_instance = azentspublicclient.ChatGPTOAuthV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Start Device
        api_response = api_instance.chatgpt_oauth_v1_start_device(handle)
        print("The response of ChatGPTOAuthV1Api->chatgpt_oauth_v1_start_device:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatGPTOAuthV1Api->chatgpt_oauth_v1_start_device: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**ChatGPTOAuthDeviceStartResponse**](ChatGPTOAuthDeviceStartResponse.md)

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
