# azentspublicclient.AgentRuntimeV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**agent_runtime_v1_get_agent_runtime**](AgentRuntimeV1Api.md#agent_runtime_v1_get_agent_runtime) | **GET** /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime | Get Agent Runtime
[**agent_runtime_v1_observe_agent_runtime**](AgentRuntimeV1Api.md#agent_runtime_v1_observe_agent_runtime) | **POST** /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/observe | Observe Agent Runtime
[**agent_runtime_v1_reset_agent_runtime**](AgentRuntimeV1Api.md#agent_runtime_v1_reset_agent_runtime) | **POST** /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/reset | Reset Agent Runtime
[**agent_runtime_v1_restart_agent_runtime**](AgentRuntimeV1Api.md#agent_runtime_v1_restart_agent_runtime) | **POST** /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/restart | Restart Agent Runtime
[**agent_runtime_v1_start_agent_runtime**](AgentRuntimeV1Api.md#agent_runtime_v1_start_agent_runtime) | **POST** /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/start | Start Agent Runtime
[**agent_runtime_v1_stop_agent_runtime**](AgentRuntimeV1Api.md#agent_runtime_v1_stop_agent_runtime) | **POST** /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/stop | Stop Agent Runtime


# **agent_runtime_v1_get_agent_runtime**
> AgentRuntimeResponse agent_runtime_v1_get_agent_runtime(agent_id, handle)

Get Agent Runtime

Get Agent Runtime status.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
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
    api_instance = azentspublicclient.AgentRuntimeV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Get Agent Runtime
        api_response = api_instance.agent_runtime_v1_get_agent_runtime(agent_id, handle)
        print("The response of AgentRuntimeV1Api->agent_runtime_v1_get_agent_runtime:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentRuntimeV1Api->agent_runtime_v1_get_agent_runtime: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**AgentRuntimeResponse**](AgentRuntimeResponse.md)

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

# **agent_runtime_v1_observe_agent_runtime**
> AgentRuntimeResponse agent_runtime_v1_observe_agent_runtime(agent_id, handle)

Observe Agent Runtime

Return the Agent Runtime observe read model.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
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
    api_instance = azentspublicclient.AgentRuntimeV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Observe Agent Runtime
        api_response = api_instance.agent_runtime_v1_observe_agent_runtime(agent_id, handle)
        print("The response of AgentRuntimeV1Api->agent_runtime_v1_observe_agent_runtime:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentRuntimeV1Api->agent_runtime_v1_observe_agent_runtime: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**AgentRuntimeResponse**](AgentRuntimeResponse.md)

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

# **agent_runtime_v1_reset_agent_runtime**
> AgentRuntimeLifecycleResponse agent_runtime_v1_reset_agent_runtime(agent_id, handle, reset_agent_runtime_request)

Reset Agent Runtime

Store Agent Runtime reset command.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_lifecycle_response import AgentRuntimeLifecycleResponse
from azentspublicclient.models.reset_agent_runtime_request import ResetAgentRuntimeRequest
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
    api_instance = azentspublicclient.AgentRuntimeV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |
    reset_agent_runtime_request = azentspublicclient.ResetAgentRuntimeRequest() # ResetAgentRuntimeRequest |

    try:
        # Reset Agent Runtime
        api_response = api_instance.agent_runtime_v1_reset_agent_runtime(agent_id, handle, reset_agent_runtime_request)
        print("The response of AgentRuntimeV1Api->agent_runtime_v1_reset_agent_runtime:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentRuntimeV1Api->agent_runtime_v1_reset_agent_runtime: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |
 **reset_agent_runtime_request** | [**ResetAgentRuntimeRequest**](ResetAgentRuntimeRequest.md)|  |

### Return type

[**AgentRuntimeLifecycleResponse**](AgentRuntimeLifecycleResponse.md)

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

# **agent_runtime_v1_restart_agent_runtime**
> AgentRuntimeLifecycleResponse agent_runtime_v1_restart_agent_runtime(agent_id, handle)

Restart Agent Runtime

Store Agent Runtime restart command.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_lifecycle_response import AgentRuntimeLifecycleResponse
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
    api_instance = azentspublicclient.AgentRuntimeV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Restart Agent Runtime
        api_response = api_instance.agent_runtime_v1_restart_agent_runtime(agent_id, handle)
        print("The response of AgentRuntimeV1Api->agent_runtime_v1_restart_agent_runtime:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentRuntimeV1Api->agent_runtime_v1_restart_agent_runtime: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**AgentRuntimeLifecycleResponse**](AgentRuntimeLifecycleResponse.md)

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

# **agent_runtime_v1_start_agent_runtime**
> AgentRuntimeLifecycleResponse agent_runtime_v1_start_agent_runtime(agent_id, handle)

Start Agent Runtime

Store Agent Runtime start desired state.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_lifecycle_response import AgentRuntimeLifecycleResponse
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
    api_instance = azentspublicclient.AgentRuntimeV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Start Agent Runtime
        api_response = api_instance.agent_runtime_v1_start_agent_runtime(agent_id, handle)
        print("The response of AgentRuntimeV1Api->agent_runtime_v1_start_agent_runtime:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentRuntimeV1Api->agent_runtime_v1_start_agent_runtime: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**AgentRuntimeLifecycleResponse**](AgentRuntimeLifecycleResponse.md)

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

# **agent_runtime_v1_stop_agent_runtime**
> AgentRuntimeLifecycleResponse agent_runtime_v1_stop_agent_runtime(agent_id, handle)

Stop Agent Runtime

Store Agent Runtime stop desired state.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_runtime_lifecycle_response import AgentRuntimeLifecycleResponse
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
    api_instance = azentspublicclient.AgentRuntimeV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Stop Agent Runtime
        api_response = api_instance.agent_runtime_v1_stop_agent_runtime(agent_id, handle)
        print("The response of AgentRuntimeV1Api->agent_runtime_v1_stop_agent_runtime:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentRuntimeV1Api->agent_runtime_v1_stop_agent_runtime: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**AgentRuntimeLifecycleResponse**](AgentRuntimeLifecycleResponse.md)

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
