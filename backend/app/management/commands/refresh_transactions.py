from django.core.management.base import BaseCommand
from app.models import User, Account
from app.db_methods import refresh_transactions_for_account
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Refreshes transactions for all accounts of all users'

    def handle(self, *args, **kwargs):
        start_time = timezone.now()
        logger.info(f"Starting transaction refresh at {start_time}")
        
        try:
            # Get all users
            users = User.objects.all()
            total_accounts = 0
            successful_refreshes = 0
            
            for user in users:
                logger.info(f"Processing accounts for user: {user.name}")
                accounts = Account.objects.filter(user=user)
                
                for account in accounts:
                    total_accounts += 1
                    try:
                        refresh_transactions_for_account(account)
                        successful_refreshes += 1
                        logger.info(f"Successfully refreshed transactions for account: {account.name}")
                    except Exception as e:
                        logger.error(f"Error refreshing transactions for account {account.name}: {str(e)}")
            
            end_time = timezone.now()
            duration = end_time - start_time
            
            logger.info(f"Transaction refresh completed at {end_time}")
            logger.info(f"Duration: {duration}")
            logger.info(f"Processed {total_accounts} accounts, {successful_refreshes} successful refreshes")
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully refreshed transactions for {successful_refreshes}/{total_accounts} accounts'
                )
            )
            
        except Exception as e:
            logger.error(f"Fatal error during transaction refresh: {str(e)}")
            self.stdout.write(
                self.style.ERROR(f'Error refreshing transactions: {str(e)}')
            ) 