# azentspublicclient.ScheduledTaskV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**scheduled_task_v1_create_scheduled_task**](ScheduledTaskV1Api.md#scheduled_task_v1_create_scheduled_task) | **POST** /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks | Create Scheduled Task
[**scheduled_task_v1_delete_scheduled_task**](ScheduledTaskV1Api.md#scheduled_task_v1_delete_scheduled_task) | **DELETE** /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id} | Delete Scheduled Task
[**scheduled_task_v1_get_scheduled_task**](ScheduledTaskV1Api.md#scheduled_task_v1_get_scheduled_task) | **GET** /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id} | Get Scheduled Task
[**scheduled_task_v1_get_scheduled_task_cycle**](ScheduledTaskV1Api.md#scheduled_task_v1_get_scheduled_task_cycle) | **GET** /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id}/cycle | Get Scheduled Task Cycle
[**scheduled_task_v1_list_scheduled_tasks**](ScheduledTaskV1Api.md#scheduled_task_v1_list_scheduled_tasks) | **GET** /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks | List Scheduled Tasks
[**scheduled_task_v1_replace_scheduled_task**](ScheduledTaskV1Api.md#scheduled_task_v1_replace_scheduled_task) | **PUT** /scheduled-task/v1/workspaces/{handle}/agents/{agent_id}/scheduled-tasks/{task_id} | Replace Scheduled Task


# **scheduled_task_v1_create_scheduled_task**
> ScheduledTaskResponse scheduled_task_v1_create_scheduled_task(agent_id, handle, scheduled_task_create_request)

Create Scheduled Task

Create a Task for one existing authorized Session.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.scheduled_task_create_request import ScheduledTaskCreateRequest
from azentspublicclient.models.scheduled_task_response import ScheduledTaskResponse
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
    api_instance = azentspublicclient.ScheduledTaskV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    scheduled_task_create_request = azentspublicclient.ScheduledTaskCreateRequest() # ScheduledTaskCreateRequest | 

    try:
        # Create Scheduled Task
        api_response = api_instance.scheduled_task_v1_create_scheduled_task(agent_id, handle, scheduled_task_create_request)
        print("The response of ScheduledTaskV1Api->scheduled_task_v1_create_scheduled_task:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ScheduledTaskV1Api->scheduled_task_v1_create_scheduled_task: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **scheduled_task_create_request** | [**ScheduledTaskCreateRequest**](ScheduledTaskCreateRequest.md)|  | 

### Return type

[**ScheduledTaskResponse**](ScheduledTaskResponse.md)

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

# **scheduled_task_v1_delete_scheduled_task**
> scheduled_task_v1_delete_scheduled_task(agent_id, task_id, handle)

Delete Scheduled Task

Permanently delete one exact authorized Scheduled Task.

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
    api_instance = azentspublicclient.ScheduledTaskV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    task_id = 'task_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Delete Scheduled Task
        api_instance.scheduled_task_v1_delete_scheduled_task(agent_id, task_id, handle)
    except Exception as e:
        print("Exception when calling ScheduledTaskV1Api->scheduled_task_v1_delete_scheduled_task: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **task_id** | **str**|  | 
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

# **scheduled_task_v1_get_scheduled_task**
> ScheduledTaskResponse scheduled_task_v1_get_scheduled_task(agent_id, task_id, handle)

Get Scheduled Task

Get one exact authorized Scheduled Task.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.scheduled_task_response import ScheduledTaskResponse
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
    api_instance = azentspublicclient.ScheduledTaskV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    task_id = 'task_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Scheduled Task
        api_response = api_instance.scheduled_task_v1_get_scheduled_task(agent_id, task_id, handle)
        print("The response of ScheduledTaskV1Api->scheduled_task_v1_get_scheduled_task:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ScheduledTaskV1Api->scheduled_task_v1_get_scheduled_task: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **task_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ScheduledTaskResponse**](ScheduledTaskResponse.md)

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

# **scheduled_task_v1_get_scheduled_task_cycle**
> ScheduledTaskCurrentCycleEnvelope scheduled_task_v1_get_scheduled_task_cycle(agent_id, task_id, handle)

Get Scheduled Task Cycle

Read the sanitized current-cycle projection.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.scheduled_task_current_cycle_envelope import ScheduledTaskCurrentCycleEnvelope
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
    api_instance = azentspublicclient.ScheduledTaskV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    task_id = 'task_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Get Scheduled Task Cycle
        api_response = api_instance.scheduled_task_v1_get_scheduled_task_cycle(agent_id, task_id, handle)
        print("The response of ScheduledTaskV1Api->scheduled_task_v1_get_scheduled_task_cycle:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ScheduledTaskV1Api->scheduled_task_v1_get_scheduled_task_cycle: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **task_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**ScheduledTaskCurrentCycleEnvelope**](ScheduledTaskCurrentCycleEnvelope.md)

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

# **scheduled_task_v1_list_scheduled_tasks**
> ScheduledTaskListResponse scheduled_task_v1_list_scheduled_tasks(agent_id, handle, session_id=session_id)

List Scheduled Tasks

List every Task in one selected or all authorized Agent Sessions.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.scheduled_task_list_response import ScheduledTaskListResponse
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
    api_instance = azentspublicclient.ScheduledTaskV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    handle = 'handle_example' # str | 
    session_id = 'session_id_example' # str |  (optional)

    try:
        # List Scheduled Tasks
        api_response = api_instance.scheduled_task_v1_list_scheduled_tasks(agent_id, handle, session_id=session_id)
        print("The response of ScheduledTaskV1Api->scheduled_task_v1_list_scheduled_tasks:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ScheduledTaskV1Api->scheduled_task_v1_list_scheduled_tasks: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **handle** | **str**|  | 
 **session_id** | **str**|  | [optional] 

### Return type

[**ScheduledTaskListResponse**](ScheduledTaskListResponse.md)

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

# **scheduled_task_v1_replace_scheduled_task**
> ScheduledTaskResponse scheduled_task_v1_replace_scheduled_task(agent_id, task_id, handle, scheduled_task_replace_request)

Replace Scheduled Task

Replace editable fields that govern future work.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.scheduled_task_replace_request import ScheduledTaskReplaceRequest
from azentspublicclient.models.scheduled_task_response import ScheduledTaskResponse
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
    api_instance = azentspublicclient.ScheduledTaskV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    task_id = 'task_id_example' # str | 
    handle = 'handle_example' # str | 
    scheduled_task_replace_request = azentspublicclient.ScheduledTaskReplaceRequest() # ScheduledTaskReplaceRequest | 

    try:
        # Replace Scheduled Task
        api_response = api_instance.scheduled_task_v1_replace_scheduled_task(agent_id, task_id, handle, scheduled_task_replace_request)
        print("The response of ScheduledTaskV1Api->scheduled_task_v1_replace_scheduled_task:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ScheduledTaskV1Api->scheduled_task_v1_replace_scheduled_task: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **task_id** | **str**|  | 
 **handle** | **str**|  | 
 **scheduled_task_replace_request** | [**ScheduledTaskReplaceRequest**](ScheduledTaskReplaceRequest.md)|  | 

### Return type

[**ScheduledTaskResponse**](ScheduledTaskResponse.md)

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

