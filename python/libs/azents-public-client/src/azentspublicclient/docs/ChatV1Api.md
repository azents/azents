# azentspublicclient.ChatV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**chat_v1_approve_agent_project_registration_request**](ChatV1Api.md#chat_v1_approve_agent_project_registration_request) | **POST** /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests/{request_id}/approve | Approve Agent Project Registration Request
[**chat_v1_archive_agent_session**](ChatV1Api.md#chat_v1_archive_agent_session) | **POST** /chat/v1/agents/{agent_id}/sessions/{session_id}/archive | Archive Agent Session
[**chat_v1_bulk_delete_agent_workspace_paths**](ChatV1Api.md#chat_v1_bulk_delete_agent_workspace_paths) | **DELETE** /chat/v1/agents/{agent_id}/workspace/files/bulk | Bulk Delete Agent Workspace Paths
[**chat_v1_bulk_move_agent_workspace_paths**](ChatV1Api.md#chat_v1_bulk_move_agent_workspace_paths) | **POST** /chat/v1/agents/{agent_id}/workspace/move/bulk | Bulk Move Agent Workspace Paths
[**chat_v1_create_agent_workspace_directory**](ChatV1Api.md#chat_v1_create_agent_workspace_directory) | **POST** /chat/v1/agents/{agent_id}/workspace/directories | Create Agent Workspace Directory
[**chat_v1_create_input**](ChatV1Api.md#chat_v1_create_input) | **POST** /chat/v1/sessions/{session_id}/inputs | Create Input
[**chat_v1_create_team_agent_session**](ChatV1Api.md#chat_v1_create_team_agent_session) | **POST** /chat/v1/agents/{agent_id}/sessions | Create Team Agent Session
[**chat_v1_create_team_agent_session_message**](ChatV1Api.md#chat_v1_create_team_agent_session_message) | **POST** /chat/v1/agents/{agent_id}/sessions/messages | Create Team Agent Session Message
[**chat_v1_delete_agent_project**](ChatV1Api.md#chat_v1_delete_agent_project) | **DELETE** /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/{project_id} | Delete Agent Project
[**chat_v1_delete_agent_workspace_path**](ChatV1Api.md#chat_v1_delete_agent_workspace_path) | **DELETE** /chat/v1/agents/{agent_id}/workspace/files | Delete Agent Workspace Path
[**chat_v1_delete_exchange_file**](ChatV1Api.md#chat_v1_delete_exchange_file) | **DELETE** /chat/v1/exchange-files/{file_id} | Delete Exchange File
[**chat_v1_delete_input_buffer**](ChatV1Api.md#chat_v1_delete_input_buffer) | **DELETE** /chat/v1/sessions/{session_id}/input-buffers/{buffer_id} | Delete Input Buffer
[**chat_v1_delete_session**](ChatV1Api.md#chat_v1_delete_session) | **DELETE** /chat/v1/sessions/{session_id} | Delete Session
[**chat_v1_download_agent_workspace_file**](ChatV1Api.md#chat_v1_download_agent_workspace_file) | **GET** /chat/v1/agents/{agent_id}/workspace/download | Download Agent Workspace File
[**chat_v1_download_exchange_file**](ChatV1Api.md#chat_v1_download_exchange_file) | **GET** /chat/v1/exchange-files/{file_id}/download | Download Exchange File
[**chat_v1_edit_message**](ChatV1Api.md#chat_v1_edit_message) | **POST** /chat/v1/sessions/{session_id}/edit-message | Edit Message
[**chat_v1_get_agent_session**](ChatV1Api.md#chat_v1_get_agent_session) | **GET** /chat/v1/agents/{agent_id}/sessions/{session_id} | Get Agent Session
[**chat_v1_get_agent_session_context**](ChatV1Api.md#chat_v1_get_agent_session_context) | **GET** /chat/v1/agents/{agent_id}/sessions/{session_id}/context | Get Agent Session Context
[**chat_v1_get_agent_session_project_defaults**](ChatV1Api.md#chat_v1_get_agent_session_project_defaults) | **GET** /chat/v1/agents/{agent_id}/session-project-defaults | Get Agent Session Project Defaults
[**chat_v1_get_agent_workspace**](ChatV1Api.md#chat_v1_get_agent_workspace) | **GET** /chat/v1/agents/{agent_id}/workspace | Get Agent Workspace
[**chat_v1_get_session_project_browser_manifest**](ChatV1Api.md#chat_v1_get_session_project_browser_manifest) | **GET** /chat/v1/agents/{agent_id}/sessions/{session_id}/workspace/project-browser-manifest | Get Session Project Browser Manifest
[**chat_v1_get_team_primary_agent_session**](ChatV1Api.md#chat_v1_get_team_primary_agent_session) | **GET** /chat/v1/agents/{agent_id}/team-primary-session | Get Team Primary Agent Session
[**chat_v1_issue_ws_ticket**](ChatV1Api.md#chat_v1_issue_ws_ticket) | **POST** /chat/v1/ticket | Issue Ws Ticket
[**chat_v1_list_agent_project_presets**](ChatV1Api.md#chat_v1_list_agent_project_presets) | **GET** /chat/v1/agents/{agent_id}/project-presets | List Agent Project Presets
[**chat_v1_list_agent_project_registration_requests**](ChatV1Api.md#chat_v1_list_agent_project_registration_requests) | **GET** /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests | List Agent Project Registration Requests
[**chat_v1_list_agent_projects**](ChatV1Api.md#chat_v1_list_agent_projects) | **GET** /chat/v1/agents/{agent_id}/sessions/{session_id}/projects | List Agent Projects
[**chat_v1_list_agent_sessions**](ChatV1Api.md#chat_v1_list_agent_sessions) | **GET** /chat/v1/agents/{agent_id}/sessions | List Agent Sessions
[**chat_v1_list_history_events**](ChatV1Api.md#chat_v1_list_history_events) | **GET** /chat/v1/sessions/{session_id}/history | List History Events
[**chat_v1_list_input_actions**](ChatV1Api.md#chat_v1_list_input_actions) | **GET** /chat/v1/sessions/{session_id}/actions | List Input Actions
[**chat_v1_list_live_events**](ChatV1Api.md#chat_v1_list_live_events) | **GET** /chat/v1/sessions/{session_id}/live | List Live Events
[**chat_v1_list_sessions**](ChatV1Api.md#chat_v1_list_sessions) | **GET** /chat/v1/workspaces/{handle}/sessions | List Sessions
[**chat_v1_move_agent_workspace_path**](ChatV1Api.md#chat_v1_move_agent_workspace_path) | **POST** /chat/v1/agents/{agent_id}/workspace/move | Move Agent Workspace Path
[**chat_v1_preview_project_browser_manifest**](ChatV1Api.md#chat_v1_preview_project_browser_manifest) | **POST** /chat/v1/agents/{agent_id}/workspace/project-browser-manifest/preview | Preview Project Browser Manifest
[**chat_v1_read_agent_workspace_path**](ChatV1Api.md#chat_v1_read_agent_workspace_path) | **GET** /chat/v1/agents/{agent_id}/workspace/files | Read Agent Workspace Path
[**chat_v1_register_agent_project**](ChatV1Api.md#chat_v1_register_agent_project) | **POST** /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register | Register Agent Project
[**chat_v1_reject_agent_project_registration_request**](ChatV1Api.md#chat_v1_reject_agent_project_registration_request) | **POST** /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests/{request_id}/reject | Reject Agent Project Registration Request
[**chat_v1_stat_agent_workspace_path**](ChatV1Api.md#chat_v1_stat_agent_workspace_path) | **GET** /chat/v1/agents/{agent_id}/workspace/stat | Stat Agent Workspace Path
[**chat_v1_stop_session_run**](ChatV1Api.md#chat_v1_stop_session_run) | **POST** /chat/v1/sessions/{session_id}/stop | Stop Session Run
[**chat_v1_update_agent_session_title**](ChatV1Api.md#chat_v1_update_agent_session_title) | **PATCH** /chat/v1/sessions/{session_id}/title | Update Agent Session Title
[**chat_v1_update_session_goal**](ChatV1Api.md#chat_v1_update_session_goal) | **PATCH** /chat/v1/sessions/{session_id}/goal | Update Session Goal
[**chat_v1_update_session_goal_status**](ChatV1Api.md#chat_v1_update_session_goal_status) | **PATCH** /chat/v1/sessions/{session_id}/goal/status | Update Session Goal Status
[**chat_v1_upload_file_for_agent**](ChatV1Api.md#chat_v1_upload_file_for_agent) | **POST** /chat/v1/agents/{agent_id}/upload | Upload File For Agent


# **chat_v1_approve_agent_project_registration_request**
> SessionWorkspaceProjectResponse chat_v1_approve_agent_project_registration_request(agent_id, session_id, request_id)

Approve Agent Project Registration Request

Approve an AgentSession Project registration request.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.session_workspace_project_response import SessionWorkspaceProjectResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |
    request_id = 'request_id_example' # str |

    try:
        # Approve Agent Project Registration Request
        api_response = api_instance.chat_v1_approve_agent_project_registration_request(agent_id, session_id, request_id)
        print("The response of ChatV1Api->chat_v1_approve_agent_project_registration_request:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_approve_agent_project_registration_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |
 **request_id** | **str**|  |

### Return type

[**SessionWorkspaceProjectResponse**](SessionWorkspaceProjectResponse.md)

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

# **chat_v1_archive_agent_session**
> chat_v1_archive_agent_session(agent_id, session_id)

Archive Agent Session

Archive a non-primary inactive AgentSession.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |

    try:
        # Archive Agent Session
        api_instance.chat_v1_archive_agent_session(agent_id, session_id)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_archive_agent_session: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |

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

# **chat_v1_bulk_delete_agent_workspace_paths**
> AgentWorkspaceBulkDeleteResponse chat_v1_bulk_delete_agent_workspace_paths(agent_id, agent_workspace_bulk_delete_request)

Bulk Delete Agent Workspace Paths

Delete multiple Agent Workspace files or directories.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_bulk_delete_request import AgentWorkspaceBulkDeleteRequest
from azentspublicclient.models.agent_workspace_bulk_delete_response import AgentWorkspaceBulkDeleteResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_workspace_bulk_delete_request = azentspublicclient.AgentWorkspaceBulkDeleteRequest() # AgentWorkspaceBulkDeleteRequest |

    try:
        # Bulk Delete Agent Workspace Paths
        api_response = api_instance.chat_v1_bulk_delete_agent_workspace_paths(agent_id, agent_workspace_bulk_delete_request)
        print("The response of ChatV1Api->chat_v1_bulk_delete_agent_workspace_paths:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_bulk_delete_agent_workspace_paths: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_workspace_bulk_delete_request** | [**AgentWorkspaceBulkDeleteRequest**](AgentWorkspaceBulkDeleteRequest.md)|  |

### Return type

[**AgentWorkspaceBulkDeleteResponse**](AgentWorkspaceBulkDeleteResponse.md)

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

# **chat_v1_bulk_move_agent_workspace_paths**
> AgentWorkspaceBulkMoveResponse chat_v1_bulk_move_agent_workspace_paths(agent_id, agent_workspace_bulk_move_request)

Bulk Move Agent Workspace Paths

Move multiple Agent Workspace files or directories.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_bulk_move_request import AgentWorkspaceBulkMoveRequest
from azentspublicclient.models.agent_workspace_bulk_move_response import AgentWorkspaceBulkMoveResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_workspace_bulk_move_request = azentspublicclient.AgentWorkspaceBulkMoveRequest() # AgentWorkspaceBulkMoveRequest |

    try:
        # Bulk Move Agent Workspace Paths
        api_response = api_instance.chat_v1_bulk_move_agent_workspace_paths(agent_id, agent_workspace_bulk_move_request)
        print("The response of ChatV1Api->chat_v1_bulk_move_agent_workspace_paths:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_bulk_move_agent_workspace_paths: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_workspace_bulk_move_request** | [**AgentWorkspaceBulkMoveRequest**](AgentWorkspaceBulkMoveRequest.md)|  |

### Return type

[**AgentWorkspaceBulkMoveResponse**](AgentWorkspaceBulkMoveResponse.md)

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

# **chat_v1_create_agent_workspace_directory**
> AgentWorkspaceMutationResponse chat_v1_create_agent_workspace_directory(agent_id, agent_workspace_mkdir_request)

Create Agent Workspace Directory

Create an Agent Workspace directory.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_mkdir_request import AgentWorkspaceMkdirRequest
from azentspublicclient.models.agent_workspace_mutation_response import AgentWorkspaceMutationResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_workspace_mkdir_request = azentspublicclient.AgentWorkspaceMkdirRequest() # AgentWorkspaceMkdirRequest |

    try:
        # Create Agent Workspace Directory
        api_response = api_instance.chat_v1_create_agent_workspace_directory(agent_id, agent_workspace_mkdir_request)
        print("The response of ChatV1Api->chat_v1_create_agent_workspace_directory:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_create_agent_workspace_directory: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_workspace_mkdir_request** | [**AgentWorkspaceMkdirRequest**](AgentWorkspaceMkdirRequest.md)|  |

### Return type

[**AgentWorkspaceMutationResponse**](AgentWorkspaceMutationResponse.md)

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

# **chat_v1_create_input**
> ChatWriteResponse chat_v1_create_input(session_id, chat_input_write_request, timezone=timezone)

Create Input

Accept a composer input at the REST boundary.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_input_write_request import ChatInputWriteRequest
from azentspublicclient.models.chat_write_response import ChatWriteResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    chat_input_write_request = azentspublicclient.ChatInputWriteRequest() # ChatInputWriteRequest |
    timezone = 'timezone_example' # str |  (optional)

    try:
        # Create Input
        api_response = api_instance.chat_v1_create_input(session_id, chat_input_write_request, timezone=timezone)
        print("The response of ChatV1Api->chat_v1_create_input:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_create_input: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **chat_input_write_request** | [**ChatInputWriteRequest**](ChatInputWriteRequest.md)|  |
 **timezone** | **str**|  | [optional]

### Return type

[**ChatWriteResponse**](ChatWriteResponse.md)

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

# **chat_v1_create_team_agent_session**
> AgentSessionResponse chat_v1_create_team_agent_session(agent_id, agent_session_create_request)

Create Team Agent Session

Create a non-primary team AgentSession for an Agent.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_create_request import AgentSessionCreateRequest
from azentspublicclient.models.agent_session_response import AgentSessionResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_session_create_request = azentspublicclient.AgentSessionCreateRequest() # AgentSessionCreateRequest |

    try:
        # Create Team Agent Session
        api_response = api_instance.chat_v1_create_team_agent_session(agent_id, agent_session_create_request)
        print("The response of ChatV1Api->chat_v1_create_team_agent_session:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_create_team_agent_session: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_session_create_request** | [**AgentSessionCreateRequest**](AgentSessionCreateRequest.md)|  |

### Return type

[**AgentSessionResponse**](AgentSessionResponse.md)

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

# **chat_v1_create_team_agent_session_message**
> ChatWriteResponse chat_v1_create_team_agent_session_message(agent_id, chat_session_create_message_write_request, timezone=timezone)

Create Team Agent Session Message

Create a team AgentSession and accept its first message.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_session_create_message_write_request import ChatSessionCreateMessageWriteRequest
from azentspublicclient.models.chat_write_response import ChatWriteResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    chat_session_create_message_write_request = azentspublicclient.ChatSessionCreateMessageWriteRequest() # ChatSessionCreateMessageWriteRequest |
    timezone = 'timezone_example' # str |  (optional)

    try:
        # Create Team Agent Session Message
        api_response = api_instance.chat_v1_create_team_agent_session_message(agent_id, chat_session_create_message_write_request, timezone=timezone)
        print("The response of ChatV1Api->chat_v1_create_team_agent_session_message:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_create_team_agent_session_message: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **chat_session_create_message_write_request** | [**ChatSessionCreateMessageWriteRequest**](ChatSessionCreateMessageWriteRequest.md)|  |
 **timezone** | **str**|  | [optional]

### Return type

[**ChatWriteResponse**](ChatWriteResponse.md)

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

# **chat_v1_delete_agent_project**
> chat_v1_delete_agent_project(agent_id, session_id, project_id)

Delete Agent Project

Delete a Project registry row for an AgentSession.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |
    project_id = 'project_id_example' # str |

    try:
        # Delete Agent Project
        api_instance.chat_v1_delete_agent_project(agent_id, session_id, project_id)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_delete_agent_project: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |
 **project_id** | **str**|  |

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

# **chat_v1_delete_agent_workspace_path**
> AgentWorkspaceMutationResponse chat_v1_delete_agent_workspace_path(agent_id, agent_workspace_delete_request)

Delete Agent Workspace Path

Delete an Agent Workspace file or directory.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_delete_request import AgentWorkspaceDeleteRequest
from azentspublicclient.models.agent_workspace_mutation_response import AgentWorkspaceMutationResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_workspace_delete_request = azentspublicclient.AgentWorkspaceDeleteRequest() # AgentWorkspaceDeleteRequest |

    try:
        # Delete Agent Workspace Path
        api_response = api_instance.chat_v1_delete_agent_workspace_path(agent_id, agent_workspace_delete_request)
        print("The response of ChatV1Api->chat_v1_delete_agent_workspace_path:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_delete_agent_workspace_path: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_workspace_delete_request** | [**AgentWorkspaceDeleteRequest**](AgentWorkspaceDeleteRequest.md)|  |

### Return type

[**AgentWorkspaceMutationResponse**](AgentWorkspaceMutationResponse.md)

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

# **chat_v1_delete_exchange_file**
> chat_v1_delete_exchange_file(file_id)

Delete Exchange File

Delete an Exchange file.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    file_id = 'file_id_example' # str |

    try:
        # Delete Exchange File
        api_instance.chat_v1_delete_exchange_file(file_id)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_delete_exchange_file: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **file_id** | **str**|  |

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

# **chat_v1_delete_input_buffer**
> chat_v1_delete_input_buffer(session_id, buffer_id)

Delete Input Buffer

Idempotently delete the pending input buffer.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    buffer_id = 'buffer_id_example' # str |

    try:
        # Delete Input Buffer
        api_instance.chat_v1_delete_input_buffer(session_id, buffer_id)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_delete_input_buffer: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **buffer_id** | **str**|  |

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

# **chat_v1_delete_session**
> chat_v1_delete_session(session_id)

Delete Session

Delete a session and related files. Only the owner can delete it.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |

    try:
        # Delete Session
        api_instance.chat_v1_delete_session(session_id)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_delete_session: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |

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

# **chat_v1_download_agent_workspace_file**
> object chat_v1_download_agent_workspace_file(agent_id, path)

Download Agent Workspace File

Download an Agent Workspace file.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    path = 'path_example' # str | Agent Workspace file path to download

    try:
        # Download Agent Workspace File
        api_response = api_instance.chat_v1_download_agent_workspace_file(agent_id, path)
        print("The response of ChatV1Api->chat_v1_download_agent_workspace_file:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_download_agent_workspace_file: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **path** | **str**| Agent Workspace file path to download |

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

# **chat_v1_download_exchange_file**
> bytearray chat_v1_download_exchange_file(file_id)

Download Exchange File

Download an Exchange file.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    file_id = 'file_id_example' # str |

    try:
        # Download Exchange File
        api_response = api_instance.chat_v1_download_exchange_file(file_id)
        print("The response of ChatV1Api->chat_v1_download_exchange_file:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_download_exchange_file: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **file_id** | **str**|  |

### Return type

**bytearray**

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/octet-stream, application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Exchange file bytes |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **chat_v1_edit_message**
> ChatWriteResponse chat_v1_edit_message(session_id, chat_edit_message_write_request, timezone=timezone)

Edit Message

Accept an existing user message edit at the REST boundary.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_edit_message_write_request import ChatEditMessageWriteRequest
from azentspublicclient.models.chat_write_response import ChatWriteResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    chat_edit_message_write_request = azentspublicclient.ChatEditMessageWriteRequest() # ChatEditMessageWriteRequest |
    timezone = 'timezone_example' # str |  (optional)

    try:
        # Edit Message
        api_response = api_instance.chat_v1_edit_message(session_id, chat_edit_message_write_request, timezone=timezone)
        print("The response of ChatV1Api->chat_v1_edit_message:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_edit_message: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **chat_edit_message_write_request** | [**ChatEditMessageWriteRequest**](ChatEditMessageWriteRequest.md)|  |
 **timezone** | **str**|  | [optional]

### Return type

[**ChatWriteResponse**](ChatWriteResponse.md)

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

# **chat_v1_get_agent_session**
> AgentSessionResponse chat_v1_get_agent_session(agent_id, session_id)

Get Agent Session

Get a URL-selected AgentSession by agent/session pair.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_response import AgentSessionResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |

    try:
        # Get Agent Session
        api_response = api_instance.chat_v1_get_agent_session(agent_id, session_id)
        print("The response of ChatV1Api->chat_v1_get_agent_session:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_get_agent_session: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |

### Return type

[**AgentSessionResponse**](AgentSessionResponse.md)

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

# **chat_v1_get_agent_session_context**
> SessionContextResponse chat_v1_get_agent_session_context(agent_id, session_id, limit=limit)

Get Agent Session Context

Return URL-selected AgentSession context inspector information.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.session_context_response import SessionContextResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |
    limit = 300 # int |  (optional) (default to 300)

    try:
        # Get Agent Session Context
        api_response = api_instance.chat_v1_get_agent_session_context(agent_id, session_id, limit=limit)
        print("The response of ChatV1Api->chat_v1_get_agent_session_context:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_get_agent_session_context: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |
 **limit** | **int**|  | [optional] [default to 300]

### Return type

[**SessionContextResponse**](SessionContextResponse.md)

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

# **chat_v1_get_agent_session_project_defaults**
> AgentSessionProjectDefaultsResponse chat_v1_get_agent_session_project_defaults(agent_id)

Get Agent Session Project Defaults

Get default Project paths for a new AgentSession.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_project_defaults_response import AgentSessionProjectDefaultsResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |

    try:
        # Get Agent Session Project Defaults
        api_response = api_instance.chat_v1_get_agent_session_project_defaults(agent_id)
        print("The response of ChatV1Api->chat_v1_get_agent_session_project_defaults:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_get_agent_session_project_defaults: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |

### Return type

[**AgentSessionProjectDefaultsResponse**](AgentSessionProjectDefaultsResponse.md)

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

# **chat_v1_get_agent_workspace**
> AgentWorkspaceResponse chat_v1_get_agent_workspace(agent_id)

Get Agent Workspace

Get Agent Workspace bootstrap status.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_response import AgentWorkspaceResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |

    try:
        # Get Agent Workspace
        api_response = api_instance.chat_v1_get_agent_workspace(agent_id)
        print("The response of ChatV1Api->chat_v1_get_agent_workspace:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_get_agent_workspace: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |

### Return type

[**AgentWorkspaceResponse**](AgentWorkspaceResponse.md)

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

# **chat_v1_get_session_project_browser_manifest**
> ProjectBrowserManifestResponse chat_v1_get_session_project_browser_manifest(agent_id, session_id)

Get Session Project Browser Manifest

Get the backend-owned Project browser manifest for an AgentSession.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.project_browser_manifest_response import ProjectBrowserManifestResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |

    try:
        # Get Session Project Browser Manifest
        api_response = api_instance.chat_v1_get_session_project_browser_manifest(agent_id, session_id)
        print("The response of ChatV1Api->chat_v1_get_session_project_browser_manifest:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_get_session_project_browser_manifest: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |

### Return type

[**ProjectBrowserManifestResponse**](ProjectBrowserManifestResponse.md)

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

# **chat_v1_get_team_primary_agent_session**
> AgentSessionResponse chat_v1_get_team_primary_agent_session(agent_id)

Get Team Primary Agent Session

Get an Agent's team primary AgentSession, creating one if absent.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_response import AgentSessionResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |

    try:
        # Get Team Primary Agent Session
        api_response = api_instance.chat_v1_get_team_primary_agent_session(agent_id)
        print("The response of ChatV1Api->chat_v1_get_team_primary_agent_session:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_get_team_primary_agent_session: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |

### Return type

[**AgentSessionResponse**](AgentSessionResponse.md)

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

# **chat_v1_issue_ws_ticket**
> WsTicketResponse chat_v1_issue_ws_ticket()

Issue Ws Ticket

Issue a short-lived HMAC ticket for WebSocket connections.

After JWT authentication, returns a signed ticket valid for 30 seconds.
The client connects to WebSocket with this ticket, without exposing the raw JWT.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.ws_ticket_response import WsTicketResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)

    try:
        # Issue Ws Ticket
        api_response = api_instance.chat_v1_issue_ws_ticket()
        print("The response of ChatV1Api->chat_v1_issue_ws_ticket:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_issue_ws_ticket: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**WsTicketResponse**](WsTicketResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **chat_v1_list_agent_project_presets**
> AgentProjectPresetListResponse chat_v1_list_agent_project_presets(agent_id)

List Agent Project Presets

List Agent Project path presets.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_project_preset_list_response import AgentProjectPresetListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |

    try:
        # List Agent Project Presets
        api_response = api_instance.chat_v1_list_agent_project_presets(agent_id)
        print("The response of ChatV1Api->chat_v1_list_agent_project_presets:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_agent_project_presets: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |

### Return type

[**AgentProjectPresetListResponse**](AgentProjectPresetListResponse.md)

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

# **chat_v1_list_agent_project_registration_requests**
> SessionWorkspaceProjectRegistrationRequestListResponse chat_v1_list_agent_project_registration_requests(agent_id, session_id)

List Agent Project Registration Requests

List Project registration requests for an AgentSession.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.session_workspace_project_registration_request_list_response import SessionWorkspaceProjectRegistrationRequestListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |

    try:
        # List Agent Project Registration Requests
        api_response = api_instance.chat_v1_list_agent_project_registration_requests(agent_id, session_id)
        print("The response of ChatV1Api->chat_v1_list_agent_project_registration_requests:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_agent_project_registration_requests: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |

### Return type

[**SessionWorkspaceProjectRegistrationRequestListResponse**](SessionWorkspaceProjectRegistrationRequestListResponse.md)

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

# **chat_v1_list_agent_projects**
> SessionWorkspaceProjectListResponse chat_v1_list_agent_projects(agent_id, session_id)

List Agent Projects

List Agent Workspace Projects for an AgentSession.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.session_workspace_project_list_response import SessionWorkspaceProjectListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |

    try:
        # List Agent Projects
        api_response = api_instance.chat_v1_list_agent_projects(agent_id, session_id)
        print("The response of ChatV1Api->chat_v1_list_agent_projects:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_agent_projects: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |

### Return type

[**SessionWorkspaceProjectListResponse**](SessionWorkspaceProjectListResponse.md)

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

# **chat_v1_list_agent_sessions**
> AgentSessionListResponse chat_v1_list_agent_sessions(agent_id)

List Agent Sessions

List active team sessions for an Agent with team primary first.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_list_response import AgentSessionListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |

    try:
        # List Agent Sessions
        api_response = api_instance.chat_v1_list_agent_sessions(agent_id)
        print("The response of ChatV1Api->chat_v1_list_agent_sessions:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_agent_sessions: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |

### Return type

[**AgentSessionListResponse**](AgentSessionListResponse.md)

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

# **chat_v1_list_history_events**
> ChatEventPageResponse chat_v1_list_history_events(session_id, limit=limit, before=before, after=after)

List History Events

Page through persisted event history for a session.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    limit = 50 # int | Number of events to query (optional) (default to 50)
    before = 'before_example' # str | Query only events before this ID, as a backward cursor (optional)
    after = 'after_example' # str | Query only events after this ID, as a forward cursor (optional)

    try:
        # List History Events
        api_response = api_instance.chat_v1_list_history_events(session_id, limit=limit, before=before, after=after)
        print("The response of ChatV1Api->chat_v1_list_history_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_history_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **limit** | **int**| Number of events to query | [optional] [default to 50]
 **before** | **str**| Query only events before this ID, as a backward cursor | [optional]
 **after** | **str**| Query only events after this ID, as a forward cursor | [optional]

### Return type

[**ChatEventPageResponse**](ChatEventPageResponse.md)

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

# **chat_v1_list_input_actions**
> InputActionListResponse chat_v1_list_input_actions(session_id)

List Input Actions

Return composer actions available for a session.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.input_action_list_response import InputActionListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |

    try:
        # List Input Actions
        api_response = api_instance.chat_v1_list_input_actions(session_id)
        print("The response of ChatV1Api->chat_v1_list_input_actions:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_input_actions: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |

### Return type

[**InputActionListResponse**](InputActionListResponse.md)

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

# **chat_v1_list_live_events**
> LiveEventListResponse chat_v1_list_live_events(session_id)

List Live Events

Get the current live event projection for a session.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.live_event_list_response import LiveEventListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |

    try:
        # List Live Events
        api_response = api_instance.chat_v1_list_live_events(session_id)
        print("The response of ChatV1Api->chat_v1_list_live_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_live_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |

### Return type

[**LiveEventListResponse**](LiveEventListResponse.md)

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

# **chat_v1_list_sessions**
> AgentSessionListResponse chat_v1_list_sessions(handle)

List Sessions

List the current user's conversation sessions in a workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_list_response import AgentSessionListResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Sessions
        api_response = api_instance.chat_v1_list_sessions(handle)
        print("The response of ChatV1Api->chat_v1_list_sessions:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_list_sessions: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**AgentSessionListResponse**](AgentSessionListResponse.md)

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

# **chat_v1_move_agent_workspace_path**
> AgentWorkspaceMoveResponse chat_v1_move_agent_workspace_path(agent_id, agent_workspace_move_request)

Move Agent Workspace Path

Move or rename an Agent Workspace file or directory.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_move_request import AgentWorkspaceMoveRequest
from azentspublicclient.models.agent_workspace_move_response import AgentWorkspaceMoveResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    agent_workspace_move_request = azentspublicclient.AgentWorkspaceMoveRequest() # AgentWorkspaceMoveRequest |

    try:
        # Move Agent Workspace Path
        api_response = api_instance.chat_v1_move_agent_workspace_path(agent_id, agent_workspace_move_request)
        print("The response of ChatV1Api->chat_v1_move_agent_workspace_path:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_move_agent_workspace_path: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **agent_workspace_move_request** | [**AgentWorkspaceMoveRequest**](AgentWorkspaceMoveRequest.md)|  |

### Return type

[**AgentWorkspaceMoveResponse**](AgentWorkspaceMoveResponse.md)

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

# **chat_v1_preview_project_browser_manifest**
> ProjectBrowserManifestResponse chat_v1_preview_project_browser_manifest(agent_id, project_browser_manifest_preview_request)

Preview Project Browser Manifest

Preview a Project browser manifest before AgentSession creation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.project_browser_manifest_preview_request import ProjectBrowserManifestPreviewRequest
from azentspublicclient.models.project_browser_manifest_response import ProjectBrowserManifestResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    project_browser_manifest_preview_request = azentspublicclient.ProjectBrowserManifestPreviewRequest() # ProjectBrowserManifestPreviewRequest |

    try:
        # Preview Project Browser Manifest
        api_response = api_instance.chat_v1_preview_project_browser_manifest(agent_id, project_browser_manifest_preview_request)
        print("The response of ChatV1Api->chat_v1_preview_project_browser_manifest:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_preview_project_browser_manifest: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **project_browser_manifest_preview_request** | [**ProjectBrowserManifestPreviewRequest**](ProjectBrowserManifestPreviewRequest.md)|  |

### Return type

[**ProjectBrowserManifestResponse**](ProjectBrowserManifestResponse.md)

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

# **chat_v1_read_agent_workspace_path**
> ResponseChatV1ReadAgentWorkspacePath chat_v1_read_agent_workspace_path(agent_id, path=path, limit=limit)

Read Agent Workspace Path

Get an Agent Workspace directory or file preview.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.response_chat_v1_read_agent_workspace_path import ResponseChatV1ReadAgentWorkspacePath
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    path = 'path_example' # str | Agent Workspace path to query (optional)
    limit = 65536 # int | Text preview byte limit (optional) (default to 65536)

    try:
        # Read Agent Workspace Path
        api_response = api_instance.chat_v1_read_agent_workspace_path(agent_id, path=path, limit=limit)
        print("The response of ChatV1Api->chat_v1_read_agent_workspace_path:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_read_agent_workspace_path: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **path** | **str**| Agent Workspace path to query | [optional]
 **limit** | **int**| Text preview byte limit | [optional] [default to 65536]

### Return type

[**ResponseChatV1ReadAgentWorkspacePath**](ResponseChatV1ReadAgentWorkspacePath.md)

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

# **chat_v1_register_agent_project**
> SessionWorkspaceProjectResponse chat_v1_register_agent_project(agent_id, session_id, session_workspace_project_register_request)

Register Agent Project

Register an existing directory in Agent Workspace as a Project.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.session_workspace_project_register_request import SessionWorkspaceProjectRegisterRequest
from azentspublicclient.models.session_workspace_project_response import SessionWorkspaceProjectResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |
    session_workspace_project_register_request = azentspublicclient.SessionWorkspaceProjectRegisterRequest() # SessionWorkspaceProjectRegisterRequest |

    try:
        # Register Agent Project
        api_response = api_instance.chat_v1_register_agent_project(agent_id, session_id, session_workspace_project_register_request)
        print("The response of ChatV1Api->chat_v1_register_agent_project:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_register_agent_project: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |
 **session_workspace_project_register_request** | [**SessionWorkspaceProjectRegisterRequest**](SessionWorkspaceProjectRegisterRequest.md)|  |

### Return type

[**SessionWorkspaceProjectResponse**](SessionWorkspaceProjectResponse.md)

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

# **chat_v1_reject_agent_project_registration_request**
> chat_v1_reject_agent_project_registration_request(agent_id, session_id, request_id)

Reject Agent Project Registration Request

Reject an AgentSession Project registration request.

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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    session_id = 'session_id_example' # str |
    request_id = 'request_id_example' # str |

    try:
        # Reject Agent Project Registration Request
        api_instance.chat_v1_reject_agent_project_registration_request(agent_id, session_id, request_id)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_reject_agent_project_registration_request: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **session_id** | **str**|  |
 **request_id** | **str**|  |

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

# **chat_v1_stat_agent_workspace_path**
> AgentWorkspaceStatResponse chat_v1_stat_agent_workspace_path(agent_id, path=path)

Stat Agent Workspace Path

Get Agent Workspace file or directory metadata.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_workspace_stat_response import AgentWorkspaceStatResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    path = 'path_example' # str | Agent Workspace path to inspect (optional)

    try:
        # Stat Agent Workspace Path
        api_response = api_instance.chat_v1_stat_agent_workspace_path(agent_id, path=path)
        print("The response of ChatV1Api->chat_v1_stat_agent_workspace_path:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_stat_agent_workspace_path: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **path** | **str**| Agent Workspace path to inspect | [optional]

### Return type

[**AgentWorkspaceStatResponse**](AgentWorkspaceStatResponse.md)

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

# **chat_v1_stop_session_run**
> ChatStopResponse chat_v1_stop_session_run(session_id)

Stop Session Run

Request active run stop for an existing session at the REST control boundary.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.chat_stop_response import ChatStopResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |

    try:
        # Stop Session Run
        api_response = api_instance.chat_v1_stop_session_run(session_id)
        print("The response of ChatV1Api->chat_v1_stop_session_run:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_stop_session_run: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |

### Return type

[**ChatStopResponse**](ChatStopResponse.md)

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

# **chat_v1_update_agent_session_title**
> AgentSessionResponse chat_v1_update_agent_session_title(session_id, agent_session_title_update_request)

Update Agent Session Title

Update or clear a user-facing AgentSession title.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.agent_session_title_update_request import AgentSessionTitleUpdateRequest
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    agent_session_title_update_request = azentspublicclient.AgentSessionTitleUpdateRequest() # AgentSessionTitleUpdateRequest |

    try:
        # Update Agent Session Title
        api_response = api_instance.chat_v1_update_agent_session_title(session_id, agent_session_title_update_request)
        print("The response of ChatV1Api->chat_v1_update_agent_session_title:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_update_agent_session_title: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **agent_session_title_update_request** | [**AgentSessionTitleUpdateRequest**](AgentSessionTitleUpdateRequest.md)|  |

### Return type

[**AgentSessionResponse**](AgentSessionResponse.md)

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

# **chat_v1_update_session_goal**
> GoalStateResponse chat_v1_update_session_goal(session_id, goal_update_request)

Update Session Goal

Update or delete the goal of an existing session.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.goal_state_response import GoalStateResponse
from azentspublicclient.models.goal_update_request import GoalUpdateRequest
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    goal_update_request = azentspublicclient.GoalUpdateRequest() # GoalUpdateRequest |

    try:
        # Update Session Goal
        api_response = api_instance.chat_v1_update_session_goal(session_id, goal_update_request)
        print("The response of ChatV1Api->chat_v1_update_session_goal:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_update_session_goal: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **goal_update_request** | [**GoalUpdateRequest**](GoalUpdateRequest.md)|  |

### Return type

[**GoalStateResponse**](GoalStateResponse.md)

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

# **chat_v1_update_session_goal_status**
> GoalStateResponse chat_v1_update_session_goal_status(session_id, goal_status_update_request)

Update Session Goal Status

Pause or resume the goal state of an existing session under user control.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.goal_state_response import GoalStateResponse
from azentspublicclient.models.goal_status_update_request import GoalStatusUpdateRequest
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    session_id = 'session_id_example' # str |
    goal_status_update_request = azentspublicclient.GoalStatusUpdateRequest() # GoalStatusUpdateRequest |

    try:
        # Update Session Goal Status
        api_response = api_instance.chat_v1_update_session_goal_status(session_id, goal_status_update_request)
        print("The response of ChatV1Api->chat_v1_update_session_goal_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_update_session_goal_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  |
 **goal_status_update_request** | [**GoalStatusUpdateRequest**](GoalStatusUpdateRequest.md)|  |

### Return type

[**GoalStateResponse**](GoalStateResponse.md)

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

# **chat_v1_upload_file_for_agent**
> UploadResponse chat_v1_upload_file_for_agent(agent_id, file)

Upload File For Agent

Upload only Exchange attachments scoped to the Agent.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.upload_response import UploadResponse
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
    api_instance = azentspublicclient.ChatV1Api(api_client)
    agent_id = 'agent_id_example' # str |
    file = 'file_example' # str |

    try:
        # Upload File For Agent
        api_response = api_instance.chat_v1_upload_file_for_agent(agent_id, file)
        print("The response of ChatV1Api->chat_v1_upload_file_for_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ChatV1Api->chat_v1_upload_file_for_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  |
 **file** | **str**|  |

### Return type

[**UploadResponse**](UploadResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: multipart/form-data
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)
