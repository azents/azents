# azentspublicclient.JoinRequestV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**join_request_v1_approve_join_request**](JoinRequestV1Api.md#join_request_v1_approve_join_request) | **POST** /join-request/v1/workspaces/{handle}/join-requests/{join_request_id}/approve | Approve Join Request
[**join_request_v1_create_join_request**](JoinRequestV1Api.md#join_request_v1_create_join_request) | **POST** /join-request/v1/workspaces/{handle}/join-requests | Create Join Request
[**join_request_v1_delete_join_request**](JoinRequestV1Api.md#join_request_v1_delete_join_request) | **DELETE** /join-request/v1/workspaces/{handle}/join-requests/{join_request_id} | Delete Join Request
[**join_request_v1_get_my_join_request**](JoinRequestV1Api.md#join_request_v1_get_my_join_request) | **GET** /join-request/v1/workspaces/{handle}/join-requests/me | Get My Join Request
[**join_request_v1_list_join_requests**](JoinRequestV1Api.md#join_request_v1_list_join_requests) | **GET** /join-request/v1/workspaces/{handle}/join-requests | List Join Requests
[**join_request_v1_mute_join_request**](JoinRequestV1Api.md#join_request_v1_mute_join_request) | **POST** /join-request/v1/workspaces/{handle}/join-requests/{join_request_id}/mute | Mute Join Request
[**join_request_v1_reject_join_request**](JoinRequestV1Api.md#join_request_v1_reject_join_request) | **POST** /join-request/v1/workspaces/{handle}/join-requests/{join_request_id}/reject | Reject Join Request


# **join_request_v1_approve_join_request**
> object join_request_v1_approve_join_request(join_request_id, handle)

Approve Join Request

Approve a join request.

Requires manager-or-higher permission.

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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    join_request_id = 'join_request_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Approve Join Request
        api_response = api_instance.join_request_v1_approve_join_request(join_request_id, handle)
        print("The response of JoinRequestV1Api->join_request_v1_approve_join_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_approve_join_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **join_request_id** | **str**|  | 
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

# **join_request_v1_create_join_request**
> JoinRequestResponse join_request_v1_create_join_request(handle, create_join_request_request)

Create Join Request

Request to join a workspace.

Any logged-in user can request this, including non-members.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.create_join_request_request import CreateJoinRequestRequest
from azentspublicclient.models.join_request_response import JoinRequestResponse
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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    handle = 'handle_example' # str | 
    create_join_request_request = azentspublicclient.CreateJoinRequestRequest() # CreateJoinRequestRequest | 

    try:
        # Create Join Request
        api_response = api_instance.join_request_v1_create_join_request(handle, create_join_request_request)
        print("The response of JoinRequestV1Api->join_request_v1_create_join_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_create_join_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **create_join_request_request** | [**CreateJoinRequestRequest**](CreateJoinRequestRequest.md)|  | 

### Return type

[**JoinRequestResponse**](JoinRequestResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **join_request_v1_delete_join_request**
> join_request_v1_delete_join_request(join_request_id, handle)

Delete Join Request

Delete a join request.

Requires manager-or-higher permission. Also used to unmute.

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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    join_request_id = 'join_request_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Delete Join Request
        api_instance.join_request_v1_delete_join_request(join_request_id, handle)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_delete_join_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **join_request_id** | **str**|  | 
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

# **join_request_v1_get_my_join_request**
> MyJoinRequestResponse join_request_v1_get_my_join_request(handle)

Get My Join Request

Get my join request status.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.my_join_request_response import MyJoinRequestResponse
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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get My Join Request
        api_response = api_instance.join_request_v1_get_my_join_request(handle)
        print("The response of JoinRequestV1Api->join_request_v1_get_my_join_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_get_my_join_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**MyJoinRequestResponse**](MyJoinRequestResponse.md)

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

# **join_request_v1_list_join_requests**
> JoinRequestListResponse join_request_v1_list_join_requests(handle)

List Join Requests

List join requests for a workspace.

Requires manager-or-higher permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.join_request_list_response import JoinRequestListResponse
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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # List Join Requests
        api_response = api_instance.join_request_v1_list_join_requests(handle)
        print("The response of JoinRequestV1Api->join_request_v1_list_join_requests:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_list_join_requests: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**JoinRequestListResponse**](JoinRequestListResponse.md)

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

# **join_request_v1_mute_join_request**
> object join_request_v1_mute_join_request(join_request_id, handle)

Mute Join Request

Mute a join request.

Requires manager-or-higher permission. Notifications are not sent on re-request.

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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    join_request_id = 'join_request_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Mute Join Request
        api_response = api_instance.join_request_v1_mute_join_request(join_request_id, handle)
        print("The response of JoinRequestV1Api->join_request_v1_mute_join_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_mute_join_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **join_request_id** | **str**|  | 
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

# **join_request_v1_reject_join_request**
> object join_request_v1_reject_join_request(join_request_id, handle)

Reject Join Request

Reject a join request.

Requires manager-or-higher permission.

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
    api_instance = azentspublicclient.JoinRequestV1Api(api_client)
    join_request_id = 'join_request_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Reject Join Request
        api_response = api_instance.join_request_v1_reject_join_request(join_request_id, handle)
        print("The response of JoinRequestV1Api->join_request_v1_reject_join_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling JoinRequestV1Api->join_request_v1_reject_join_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **join_request_id** | **str**|  | 
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

