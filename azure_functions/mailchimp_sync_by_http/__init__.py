import from common import mailchimp_sync

def main(req: HttpRequest = None) -> HttpResponse:
    return mailchimp_sync(req)


# def main(req: HttpRequest = None, mytimer: TimerRequest = None) -> HttpResponse:
#     logging.info("Azure function 'mailchimp_sync' triggered.")
#     if member_login() and obtain_admin_rights():
#         soup = execute_report()
#         data = extract_data(soup)
#         merge_field_collection = map_data_to_merge_fields(data)
#         added_count, updated_count = update_mailchimp_async(merge_field_collection)
#         if tc:
#             tc.track_event("Function executed successfully")
#             tc.flush()
    
#     response_message = (
#         f"Azure function 'mailchimp_sync' completed. "
#         f"Added: {added_count}, Updated: {updated_count}"
#     )

#     logging.info("Azure function 'mailchimp_sync' completed.")

#     return HttpResponse(response_message, status_code=200)
