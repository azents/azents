# azentspublicclient.BrowserV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**browser_v1_close_browser_page**](BrowserV1Api.md#browser_v1_close_browser_page) | **POST** /browser/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/pages/{page_id}/close | Close Browser Page
[**browser_v1_get_browser_projection**](BrowserV1Api.md#browser_v1_get_browser_projection) | **GET** /browser/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id} | Get Browser Projection


# **browser_v1_close_browser_page**
> BrowserProjectionResponse browser_v1_close_browser_page(handle, agent_id, session_id, page_id, browser_close_page_request)

Close Browser Page

Close only the exact current page under directing Session authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.browser_close_page_request import BrowserClosePageRequest
from azentspublicclient.models.browser_projection_response import BrowserProjectionResponse
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
    api_instance = azentspublicclient.BrowserV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    page_id = 'page_id_example' # str | 
    browser_close_page_request = azentspublicclient.BrowserClosePageRequest() # BrowserClosePageRequest | 

    try:
        # Close Browser Page
        api_response = api_instance.browser_v1_close_browser_page(handle, agent_id, session_id, page_id, browser_close_page_request)
        print("The response of BrowserV1Api->browser_v1_close_browser_page:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BrowserV1Api->browser_v1_close_browser_page: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **page_id** | **str**|  | 
 **browser_close_page_request** | [**BrowserClosePageRequest**](BrowserClosePageRequest.md)|  | 

### Return type

[**BrowserProjectionResponse**](BrowserProjectionResponse.md)

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

# **browser_v1_get_browser_projection**
> BrowserProjectionResponse browser_v1_get_browser_projection(handle, agent_id, session_id)

Get Browser Projection

List authorized current Browser tasks without starting any Runtime.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.browser_projection_response import BrowserProjectionResponse
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
    api_instance = azentspublicclient.BrowserV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 

    try:
        # Get Browser Projection
        api_response = api_instance.browser_v1_get_browser_projection(handle, agent_id, session_id)
        print("The response of BrowserV1Api->browser_v1_get_browser_projection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling BrowserV1Api->browser_v1_get_browser_projection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 

### Return type

[**BrowserProjectionResponse**](BrowserProjectionResponse.md)

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

