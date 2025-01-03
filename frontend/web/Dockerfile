FROM node:22.12.0

# Set the working directory
WORKDIR /app

# Copy application files to the working directory
COPY . .

# Install dependencies
RUN npm install

# Expose port 3000 for the nextjs development server
EXPOSE 3000

# Run the nextjs development server on all network interfaces
CMD ["npm", "run", "dev"]
