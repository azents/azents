# azentspublicclient.RuntimeWebV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_web_v1_approve_runtime_web_request**](RuntimeWebV1Api.md#runtime_web_v1_approve_runtime_web_request) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/requests/{request_id}/approve | Approve Runtime Web Request
[**runtime_web_v1_cancel_runtime_web_request**](RuntimeWebV1Api.md#runtime_web_v1_cancel_runtime_web_request) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/requests/{request_id}/cancel | Cancel Runtime Web Request
[**runtime_web_v1_close_runtime_web_cycle**](RuntimeWebV1Api.md#runtime_web_v1_close_runtime_web_cycle) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/cycles/{cycle_id}/close | Close Runtime Web Cycle
[**runtime_web_v1_direct_create_runtime_web_exposure**](RuntimeWebV1Api.md#runtime_web_v1_direct_create_runtime_web_exposure) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}/direct-create | Direct Create Runtime Web Exposure
[**runtime_web_v1_get_runtime_web_service_projection**](RuntimeWebV1Api.md#runtime_web_v1_get_runtime_web_service_projection) | **GET** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port} | Get Runtime Web Service Projection
[**runtime_web_v1_list_runtime_web_services**](RuntimeWebV1Api.md#runtime_web_v1_list_runtime_web_services) | **GET** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services | List Runtime Web Services
[**runtime_web_v1_prepare_runtime_web_endpoint**](RuntimeWebV1Api.md#runtime_web_v1_prepare_runtime_web_endpoint) | **PUT** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}/endpoint | Prepare Runtime Web Endpoint
[**runtime_web_v1_reject_runtime_web_request**](RuntimeWebV1Api.md#runtime_web_v1_reject_runtime_web_request) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/requests/{request_id}/reject | Reject Runtime Web Request
[**runtime_web_v1_request_runtime_web_exposure**](RuntimeWebV1Api.md#runtime_web_v1_request_runtime_web_exposure) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}/requests | Request Runtime Web Exposure


# **runtime_web_v1_approve_runtime_web_request**
> RuntimeWebServiceResponse runtime_web_v1_approve_runtime_web_request(handle, agent_id, session_id, request_id, runtime_web_approval_request)

Approve Runtime Web Request

Approve one exact pending request and displayed duration.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_approval_request import RuntimeWebApprovalRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    request_id = 'request_id_example' # str | 
    runtime_web_approval_request = azentspublicclient.RuntimeWebApprovalRequest() # RuntimeWebApprovalRequest | 

    try:
        # Approve Runtime Web Request
        api_response = api_instance.runtime_web_v1_approve_runtime_web_request(handle, agent_id, session_id, request_id, runtime_web_approval_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_approve_runtime_web_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_approve_runtime_web_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **request_id** | **str**|  | 
 **runtime_web_approval_request** | [**RuntimeWebApprovalRequest**](RuntimeWebApprovalRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_cancel_runtime_web_request**
> RuntimeWebServiceResponse runtime_web_v1_cancel_runtime_web_request(handle, agent_id, session_id, request_id, runtime_web_expected_revision_request)

Cancel Runtime Web Request

Cancel one exact pending request without closing an active exposure.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_expected_revision_request import RuntimeWebExpectedRevisionRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    request_id = 'request_id_example' # str | 
    runtime_web_expected_revision_request = azentspublicclient.RuntimeWebExpectedRevisionRequest() # RuntimeWebExpectedRevisionRequest | 

    try:
        # Cancel Runtime Web Request
        api_response = api_instance.runtime_web_v1_cancel_runtime_web_request(handle, agent_id, session_id, request_id, runtime_web_expected_revision_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_cancel_runtime_web_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_cancel_runtime_web_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **request_id** | **str**|  | 
 **runtime_web_expected_revision_request** | [**RuntimeWebExpectedRevisionRequest**](RuntimeWebExpectedRevisionRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_close_runtime_web_cycle**
> RuntimeWebServiceResponse runtime_web_v1_close_runtime_web_cycle(handle, agent_id, session_id, cycle_id, runtime_web_close_request)

Close Runtime Web Cycle

Close one exact active exposure without managing the application process.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_close_request import RuntimeWebCloseRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    cycle_id = 'cycle_id_example' # str | 
    runtime_web_close_request = azentspublicclient.RuntimeWebCloseRequest() # RuntimeWebCloseRequest | 

    try:
        # Close Runtime Web Cycle
        api_response = api_instance.runtime_web_v1_close_runtime_web_cycle(handle, agent_id, session_id, cycle_id, runtime_web_close_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_close_runtime_web_cycle:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_close_runtime_web_cycle: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **cycle_id** | **str**|  | 
 **runtime_web_close_request** | [**RuntimeWebCloseRequest**](RuntimeWebCloseRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_direct_create_runtime_web_exposure**
> RuntimeWebServiceResponse runtime_web_v1_direct_create_runtime_web_exposure(handle, agent_id, session_id, port, runtime_web_direct_create_request)

Direct Create Runtime Web Exposure

Directly create one user-confirmed finite exposure cycle.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_direct_create_request import RuntimeWebDirectCreateRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    port = 56 # int | 
    runtime_web_direct_create_request = azentspublicclient.RuntimeWebDirectCreateRequest() # RuntimeWebDirectCreateRequest | 

    try:
        # Direct Create Runtime Web Exposure
        api_response = api_instance.runtime_web_v1_direct_create_runtime_web_exposure(handle, agent_id, session_id, port, runtime_web_direct_create_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_direct_create_runtime_web_exposure:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_direct_create_runtime_web_exposure: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **port** | **int**|  | 
 **runtime_web_direct_create_request** | [**RuntimeWebDirectCreateRequest**](RuntimeWebDirectCreateRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_get_runtime_web_service_projection**
> RuntimeWebServiceResponse runtime_web_v1_get_runtime_web_service_projection(handle, agent_id, session_id, port)

Get Runtime Web Service Projection

Return one current Runtime Web service projection.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    port = 56 # int | 

    try:
        # Get Runtime Web Service Projection
        api_response = api_instance.runtime_web_v1_get_runtime_web_service_projection(handle, agent_id, session_id, port)
        print("The response of RuntimeWebV1Api->runtime_web_v1_get_runtime_web_service_projection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_get_runtime_web_service_projection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **port** | **int**|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_list_runtime_web_services**
> RuntimeWebServiceListResponse runtime_web_v1_list_runtime_web_services(handle, agent_id, session_id, offset=offset, limit=limit)

List Runtime Web Services

List bounded current Runtime Web service projections.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_service_list_response import RuntimeWebServiceListResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Runtime Web Services
        api_response = api_instance.runtime_web_v1_list_runtime_web_services(handle, agent_id, session_id, offset=offset, limit=limit)
        print("The response of RuntimeWebV1Api->runtime_web_v1_list_runtime_web_services:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_list_runtime_web_services: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**RuntimeWebServiceListResponse**](RuntimeWebServiceListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_prepare_runtime_web_endpoint**
> RuntimeWebServiceResponse runtime_web_v1_prepare_runtime_web_endpoint(handle, agent_id, session_id, port, runtime_web_prepare_request)

Prepare Runtime Web Endpoint

Prepare one stable Session-and-port endpoint without creating exposure.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_prepare_request import RuntimeWebPrepareRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    port = 56 # int | 
    runtime_web_prepare_request = azentspublicclient.RuntimeWebPrepareRequest() # RuntimeWebPrepareRequest | 

    try:
        # Prepare Runtime Web Endpoint
        api_response = api_instance.runtime_web_v1_prepare_runtime_web_endpoint(handle, agent_id, session_id, port, runtime_web_prepare_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_prepare_runtime_web_endpoint:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_prepare_runtime_web_endpoint: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **port** | **int**|  | 
 **runtime_web_prepare_request** | [**RuntimeWebPrepareRequest**](RuntimeWebPrepareRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_reject_runtime_web_request**
> RuntimeWebServiceResponse runtime_web_v1_reject_runtime_web_request(handle, agent_id, session_id, request_id, runtime_web_expected_revision_request)

Reject Runtime Web Request

Reject one exact pending request.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_expected_revision_request import RuntimeWebExpectedRevisionRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    request_id = 'request_id_example' # str | 
    runtime_web_expected_revision_request = azentspublicclient.RuntimeWebExpectedRevisionRequest() # RuntimeWebExpectedRevisionRequest | 

    try:
        # Reject Runtime Web Request
        api_response = api_instance.runtime_web_v1_reject_runtime_web_request(handle, agent_id, session_id, request_id, runtime_web_expected_revision_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_reject_runtime_web_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_reject_runtime_web_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **request_id** | **str**|  | 
 **runtime_web_expected_revision_request** | [**RuntimeWebExpectedRevisionRequest**](RuntimeWebExpectedRevisionRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_request_runtime_web_exposure**
> RuntimeWebServiceResponse runtime_web_v1_request_runtime_web_exposure(handle, agent_id, session_id, port, runtime_web_exposure_request)

Request Runtime Web Exposure

Create or return the pending request without waiting for approval.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_exposure_request import RuntimeWebExposureRequest
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
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
    api_instance = azentspublicclient.RuntimeWebV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 
    port = 56 # int | 
    runtime_web_exposure_request = azentspublicclient.RuntimeWebExposureRequest() # RuntimeWebExposureRequest | 

    try:
        # Request Runtime Web Exposure
        api_response = api_instance.runtime_web_v1_request_runtime_web_exposure(handle, agent_id, session_id, port, runtime_web_exposure_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_request_runtime_web_exposure:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_request_runtime_web_exposure: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 
 **port** | **int**|  | 
 **runtime_web_exposure_request** | [**RuntimeWebExposureRequest**](RuntimeWebExposureRequest.md)|  | 

### Return type

[**RuntimeWebServiceResponse**](RuntimeWebServiceResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Session service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state or installation configuration changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

