# azentspublicclient.RuntimeWebV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_web_v1_create_runtime_web_service**](RuntimeWebV1Api.md#runtime_web_v1_create_runtime_web_service) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services | Create Runtime Web Service
[**runtime_web_v1_delete_runtime_web_service**](RuntimeWebV1Api.md#runtime_web_v1_delete_runtime_web_service) | **DELETE** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services/{service_id} | Delete Runtime Web Service
[**runtime_web_v1_get_runtime_web_service_by_id**](RuntimeWebV1Api.md#runtime_web_v1_get_runtime_web_service_by_id) | **GET** /runtime-web/v1/services/{service_id} | Get Runtime Web Service By Id
[**runtime_web_v1_get_runtime_web_service_projection**](RuntimeWebV1Api.md#runtime_web_v1_get_runtime_web_service_projection) | **GET** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services/{service_id} | Get Runtime Web Service Projection
[**runtime_web_v1_initiate_runtime_web_separate_identity**](RuntimeWebV1Api.md#runtime_web_v1_initiate_runtime_web_separate_identity) | **POST** /runtime-web/v1/auth/separate/initiate | Initiate Runtime Web Separate Identity
[**runtime_web_v1_issue_runtime_web_separate_ticket**](RuntimeWebV1Api.md#runtime_web_v1_issue_runtime_web_separate_ticket) | **POST** /runtime-web/v1/auth/separate/ticket | Issue Runtime Web Separate Ticket
[**runtime_web_v1_issue_runtime_web_shared_identity**](RuntimeWebV1Api.md#runtime_web_v1_issue_runtime_web_shared_identity) | **POST** /runtime-web/v1/auth/shared-identity | Issue Runtime Web Shared Identity
[**runtime_web_v1_list_runtime_web_services**](RuntimeWebV1Api.md#runtime_web_v1_list_runtime_web_services) | **GET** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services | List Runtime Web Services
[**runtime_web_v1_mark_runtime_web_separate_identity_bound**](RuntimeWebV1Api.md#runtime_web_v1_mark_runtime_web_separate_identity_bound) | **POST** /runtime-web/v1/auth/separate/bound | Mark Runtime Web Separate Identity Bound
[**runtime_web_v1_reset_runtime_web_service_expiration**](RuntimeWebV1Api.md#runtime_web_v1_reset_runtime_web_service_expiration) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services/{service_id}/reset | Reset Runtime Web Service Expiration
[**runtime_web_v1_revoke_runtime_web_identity**](RuntimeWebV1Api.md#runtime_web_v1_revoke_runtime_web_identity) | **POST** /runtime-web/v1/auth/revoke-identity | Revoke Runtime Web Identity
[**runtime_web_v1_turn_off_runtime_web_service**](RuntimeWebV1Api.md#runtime_web_v1_turn_off_runtime_web_service) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services/{service_id}/off | Turn Off Runtime Web Service
[**runtime_web_v1_turn_on_runtime_web_service**](RuntimeWebV1Api.md#runtime_web_v1_turn_on_runtime_web_service) | **POST** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services/{service_id}/on | Turn On Runtime Web Service
[**runtime_web_v1_turn_on_runtime_web_service_by_id**](RuntimeWebV1Api.md#runtime_web_v1_turn_on_runtime_web_service_by_id) | **POST** /runtime-web/v1/services/{service_id}/on | Turn On Runtime Web Service By Id
[**runtime_web_v1_update_runtime_web_service**](RuntimeWebV1Api.md#runtime_web_v1_update_runtime_web_service) | **PATCH** /runtime-web/v1/workspaces/{handle}/agents/{agent_id}/services/{service_id} | Update Runtime Web Service


# **runtime_web_v1_create_runtime_web_service**
> RuntimeWebServiceResponse runtime_web_v1_create_runtime_web_service(agent_id, handle, runtime_web_create_request)

Create Runtime Web Service

Create one Agent-port service directly.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_create_request import RuntimeWebCreateRequest
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
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_web_create_request = azentspublicclient.RuntimeWebCreateRequest() # RuntimeWebCreateRequest | 

    try:
        # Create Runtime Web Service
        api_response = api_instance.runtime_web_v1_create_runtime_web_service(agent_id, handle, runtime_web_create_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_create_runtime_web_service:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_create_runtime_web_service: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **runtime_web_create_request** | [**RuntimeWebCreateRequest**](RuntimeWebCreateRequest.md)|  | 

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_delete_runtime_web_service**
> RuntimeWebDeleteResponse runtime_web_v1_delete_runtime_web_service(agent_id, service_id, handle, runtime_web_expected_revision_request)

Delete Runtime Web Service

Delete one service and retire its public address.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_delete_response import RuntimeWebDeleteResponse
from azentspublicclient.models.runtime_web_expected_revision_request import RuntimeWebExpectedRevisionRequest
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
    agent_id = 'agent_id_example' # str | 
    service_id = 'service_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_web_expected_revision_request = azentspublicclient.RuntimeWebExpectedRevisionRequest() # RuntimeWebExpectedRevisionRequest | 

    try:
        # Delete Runtime Web Service
        api_response = api_instance.runtime_web_v1_delete_runtime_web_service(agent_id, service_id, handle, runtime_web_expected_revision_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_delete_runtime_web_service:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_delete_runtime_web_service: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **service_id** | **str**|  | 
 **handle** | **str**|  | 
 **runtime_web_expected_revision_request** | [**RuntimeWebExpectedRevisionRequest**](RuntimeWebExpectedRevisionRequest.md)|  | 

### Return type

[**RuntimeWebDeleteResponse**](RuntimeWebDeleteResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_get_runtime_web_service_by_id**
> RuntimeWebServiceResponse runtime_web_v1_get_runtime_web_service_by_id(service_id)

Get Runtime Web Service By Id

Get one service for the trusted Main Web activation surface.

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
    service_id = 'service_id_example' # str | 

    try:
        # Get Runtime Web Service By Id
        api_response = api_instance.runtime_web_v1_get_runtime_web_service_by_id(service_id)
        print("The response of RuntimeWebV1Api->runtime_web_v1_get_runtime_web_service_by_id:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_get_runtime_web_service_by_id: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **service_id** | **str**|  | 

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_get_runtime_web_service_projection**
> RuntimeWebServiceResponse runtime_web_v1_get_runtime_web_service_projection(agent_id, service_id, handle)

Get Runtime Web Service Projection

Get one exact Agent-owned service.

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
    agent_id = 'agent_id_example' # str | 
    service_id = 'service_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Runtime Web Service Projection
        api_response = api_instance.runtime_web_v1_get_runtime_web_service_projection(agent_id, service_id, handle)
        print("The response of RuntimeWebV1Api->runtime_web_v1_get_runtime_web_service_projection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_get_runtime_web_service_projection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **service_id** | **str**|  | 
 **handle** | **str**|  | 

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_initiate_runtime_web_separate_identity**
> RuntimeWebSeparateInitiateResponse runtime_web_v1_initiate_runtime_web_separate_identity(runtime_web_separate_initiate_request)

Initiate Runtime Web Separate Identity

Create one Main-origin binding without a URL-carried secret.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_separate_initiate_request import RuntimeWebSeparateInitiateRequest
from azentspublicclient.models.runtime_web_separate_initiate_response import RuntimeWebSeparateInitiateResponse
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
    runtime_web_separate_initiate_request = azentspublicclient.RuntimeWebSeparateInitiateRequest() # RuntimeWebSeparateInitiateRequest | 

    try:
        # Initiate Runtime Web Separate Identity
        api_response = api_instance.runtime_web_v1_initiate_runtime_web_separate_identity(runtime_web_separate_initiate_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_initiate_runtime_web_separate_identity:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_initiate_runtime_web_separate_identity: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_web_separate_initiate_request** | [**RuntimeWebSeparateInitiateRequest**](RuntimeWebSeparateInitiateRequest.md)|  | 

### Return type

[**RuntimeWebSeparateInitiateResponse**](RuntimeWebSeparateInitiateResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**409** | The authentication exchange or installation changed. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_issue_runtime_web_separate_ticket**
> RuntimeWebSeparateTicketResponse runtime_web_v1_issue_runtime_web_separate_ticket(runtime_web_separate_bound_request)

Issue Runtime Web Separate Ticket

Issue one thirty-second ticket after the broker callback.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_separate_bound_request import RuntimeWebSeparateBoundRequest
from azentspublicclient.models.runtime_web_separate_ticket_response import RuntimeWebSeparateTicketResponse
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
    runtime_web_separate_bound_request = azentspublicclient.RuntimeWebSeparateBoundRequest() # RuntimeWebSeparateBoundRequest | 

    try:
        # Issue Runtime Web Separate Ticket
        api_response = api_instance.runtime_web_v1_issue_runtime_web_separate_ticket(runtime_web_separate_bound_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_issue_runtime_web_separate_ticket:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_issue_runtime_web_separate_ticket: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_web_separate_bound_request** | [**RuntimeWebSeparateBoundRequest**](RuntimeWebSeparateBoundRequest.md)|  | 

### Return type

[**RuntimeWebSeparateTicketResponse**](RuntimeWebSeparateTicketResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**409** | The authentication exchange or installation changed. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_issue_runtime_web_shared_identity**
> RuntimeWebIdentitySecretResponse runtime_web_v1_issue_runtime_web_shared_identity()

Issue Runtime Web Shared Identity

Mint one opaque Gateway identity for a trusted Main Web response.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_identity_secret_response import RuntimeWebIdentitySecretResponse
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

    try:
        # Issue Runtime Web Shared Identity
        api_response = api_instance.runtime_web_v1_issue_runtime_web_shared_identity()
        print("The response of RuntimeWebV1Api->runtime_web_v1_issue_runtime_web_shared_identity:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_issue_runtime_web_shared_identity: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**RuntimeWebIdentitySecretResponse**](RuntimeWebIdentitySecretResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**409** | The authentication exchange or installation changed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_list_runtime_web_services**
> RuntimeWebServiceListResponse runtime_web_v1_list_runtime_web_services(agent_id, handle, offset=offset, limit=limit)

List Runtime Web Services

List services shared by every Session of one Agent.

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
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 100 # int |  (optional) (default to 100)

    try:
        # List Runtime Web Services
        api_response = api_instance.runtime_web_v1_list_runtime_web_services(agent_id, handle, offset=offset, limit=limit)
        print("The response of RuntimeWebV1Api->runtime_web_v1_list_runtime_web_services:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_list_runtime_web_services: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 100]

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_mark_runtime_web_separate_identity_bound**
> runtime_web_v1_mark_runtime_web_separate_identity_bound(runtime_web_separate_bound_request)

Mark Runtime Web Separate Identity Bound

Record the exact broker callback under the current auth Session.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_separate_bound_request import RuntimeWebSeparateBoundRequest
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
    runtime_web_separate_bound_request = azentspublicclient.RuntimeWebSeparateBoundRequest() # RuntimeWebSeparateBoundRequest | 

    try:
        # Mark Runtime Web Separate Identity Bound
        api_instance.runtime_web_v1_mark_runtime_web_separate_identity_bound(runtime_web_separate_bound_request)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_mark_runtime_web_separate_identity_bound: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_web_separate_bound_request** | [**RuntimeWebSeparateBoundRequest**](RuntimeWebSeparateBoundRequest.md)|  | 

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
**409** | The authentication exchange or installation changed. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_reset_runtime_web_service_expiration**
> RuntimeWebServiceResponse runtime_web_v1_reset_runtime_web_service_expiration(agent_id, service_id, handle, runtime_web_expected_revision_request)

Reset Runtime Web Service Expiration

Restart one On service exposure window.

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
    agent_id = 'agent_id_example' # str | 
    service_id = 'service_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_web_expected_revision_request = azentspublicclient.RuntimeWebExpectedRevisionRequest() # RuntimeWebExpectedRevisionRequest | 

    try:
        # Reset Runtime Web Service Expiration
        api_response = api_instance.runtime_web_v1_reset_runtime_web_service_expiration(agent_id, service_id, handle, runtime_web_expected_revision_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_reset_runtime_web_service_expiration:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_reset_runtime_web_service_expiration: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **service_id** | **str**|  | 
 **handle** | **str**|  | 
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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_revoke_runtime_web_identity**
> RuntimeWebIdentityRevokeResponse runtime_web_v1_revoke_runtime_web_identity(runtime_web_identity_revoke_request)

Revoke Runtime Web Identity

Revoke a Gateway identity during trusted logout.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_identity_revoke_request import RuntimeWebIdentityRevokeRequest
from azentspublicclient.models.runtime_web_identity_revoke_response import RuntimeWebIdentityRevokeResponse
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
    runtime_web_identity_revoke_request = azentspublicclient.RuntimeWebIdentityRevokeRequest() # RuntimeWebIdentityRevokeRequest | 

    try:
        # Revoke Runtime Web Identity
        api_response = api_instance.runtime_web_v1_revoke_runtime_web_identity(runtime_web_identity_revoke_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_revoke_runtime_web_identity:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_revoke_runtime_web_identity: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_web_identity_revoke_request** | [**RuntimeWebIdentityRevokeRequest**](RuntimeWebIdentityRevokeRequest.md)|  | 

### Return type

[**RuntimeWebIdentityRevokeResponse**](RuntimeWebIdentityRevokeResponse.md)

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

# **runtime_web_v1_turn_off_runtime_web_service**
> RuntimeWebServiceResponse runtime_web_v1_turn_off_runtime_web_service(agent_id, service_id, handle, runtime_web_expected_revision_request)

Turn Off Runtime Web Service

Turn one service Off without deleting it.

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
    agent_id = 'agent_id_example' # str | 
    service_id = 'service_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_web_expected_revision_request = azentspublicclient.RuntimeWebExpectedRevisionRequest() # RuntimeWebExpectedRevisionRequest | 

    try:
        # Turn Off Runtime Web Service
        api_response = api_instance.runtime_web_v1_turn_off_runtime_web_service(agent_id, service_id, handle, runtime_web_expected_revision_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_turn_off_runtime_web_service:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_turn_off_runtime_web_service: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **service_id** | **str**|  | 
 **handle** | **str**|  | 
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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_turn_on_runtime_web_service**
> RuntimeWebServiceResponse runtime_web_v1_turn_on_runtime_web_service(agent_id, service_id, handle, runtime_web_turn_on_request)

Turn On Runtime Web Service

Turn one Off service On.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
from azentspublicclient.models.runtime_web_turn_on_request import RuntimeWebTurnOnRequest
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
    agent_id = 'agent_id_example' # str | 
    service_id = 'service_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_web_turn_on_request = azentspublicclient.RuntimeWebTurnOnRequest() # RuntimeWebTurnOnRequest | 

    try:
        # Turn On Runtime Web Service
        api_response = api_instance.runtime_web_v1_turn_on_runtime_web_service(agent_id, service_id, handle, runtime_web_turn_on_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_turn_on_runtime_web_service:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_turn_on_runtime_web_service: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **service_id** | **str**|  | 
 **handle** | **str**|  | 
 **runtime_web_turn_on_request** | [**RuntimeWebTurnOnRequest**](RuntimeWebTurnOnRequest.md)|  | 

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_turn_on_runtime_web_service_by_id**
> RuntimeWebServiceResponse runtime_web_v1_turn_on_runtime_web_service_by_id(service_id, runtime_web_turn_on_request)

Turn On Runtime Web Service By Id

Turn On one service from the trusted Main Web activation surface.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
from azentspublicclient.models.runtime_web_turn_on_request import RuntimeWebTurnOnRequest
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
    service_id = 'service_id_example' # str | 
    runtime_web_turn_on_request = azentspublicclient.RuntimeWebTurnOnRequest() # RuntimeWebTurnOnRequest | 

    try:
        # Turn On Runtime Web Service By Id
        api_response = api_instance.runtime_web_v1_turn_on_runtime_web_service_by_id(service_id, runtime_web_turn_on_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_turn_on_runtime_web_service_by_id:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_turn_on_runtime_web_service_by_id: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **service_id** | **str**|  | 
 **runtime_web_turn_on_request** | [**RuntimeWebTurnOnRequest**](RuntimeWebTurnOnRequest.md)|  | 

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_web_v1_update_runtime_web_service**
> RuntimeWebServiceResponse runtime_web_v1_update_runtime_web_service(agent_id, service_id, handle, runtime_web_update_request)

Update Runtime Web Service

Update label or selected duration without changing expiration.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse
from azentspublicclient.models.runtime_web_update_request import RuntimeWebUpdateRequest
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
    agent_id = 'agent_id_example' # str | 
    service_id = 'service_id_example' # str | 
    handle = 'handle_example' # str | 
    runtime_web_update_request = azentspublicclient.RuntimeWebUpdateRequest() # RuntimeWebUpdateRequest | 

    try:
        # Update Runtime Web Service
        api_response = api_instance.runtime_web_v1_update_runtime_web_service(agent_id, service_id, handle, runtime_web_update_request)
        print("The response of RuntimeWebV1Api->runtime_web_v1_update_runtime_web_service:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeWebV1Api->runtime_web_v1_update_runtime_web_service: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **service_id** | **str**|  | 
 **handle** | **str**|  | 
 **runtime_web_update_request** | [**RuntimeWebUpdateRequest**](RuntimeWebUpdateRequest.md)|  | 

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
**403** | The caller cannot disclose or manage this Agent service. |  -  |
**404** | The service resource is unavailable or intentionally hidden. |  -  |
**409** | The service state, Runtime capability, or installation changed. |  -  |
**429** | A logical Runtime Web service quota is exhausted. |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

