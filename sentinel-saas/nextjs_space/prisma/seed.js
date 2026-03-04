const { PrismaClient } = require('@prisma/client');
const bcrypt = require('bcryptjs');

const prisma = new PrismaClient();

async function main() {
    // Create admin user if it doesn't exist
    const adminEmail = 'admin@sentinel.app';
    const existing = await prisma.user.findUnique({ where: { email: adminEmail } });

    if (!existing) {
        const hashedPassword = await bcrypt.hash('admin123', 12);
        const admin = await prisma.user.create({
            data: {
                email: adminEmail,
                name: 'Admin',
                password: hashedPassword,
                role: 'admin',
                referralCode: 'godaccount',
                subscription: {
                    create: {
                        tier: 'ultra',
                        status: 'active',
                        coinScans: 50,
                    },
                },
            },
        });
        console.log('✅ Admin user created:', admin.email);
    } else {
        console.log('ℹ️ Admin user already exists:', existing.email);
    }
}

main()
    .catch(console.error)
    .finally(() => prisma.$disconnect());
